from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from northstar_api.config import get_settings
from northstar_api.database import build_engine
from northstar_api.lead_crm.channel_models import ChannelConnection, ChannelOutboundDelivery
from northstar_api.lead_crm.credentials import CredentialStoreError, credential_store
from northstar_api.lead_crm.domain import ChannelProvider
from northstar_api.models import Message
from northstar_api.services.facebook_messenger import (
    MessengerAPIError,
    messenger_client,
    normalize_messenger_api_version,
    split_messenger_text,
)
from northstar_api.workers.celery_app import celery_app

logger = structlog.get_logger(__name__)
MESSENGER_TERMINAL_STATUSES = frozenset(
    {"sent", "cancelled", "rejected", "reconnect_required", "dispatch_failed"}
)


def messenger_thread_lock_key(connection_id: UUID, recipient_id: str) -> str:
    return f"facebook-messenger-thread:{connection_id}:{recipient_id}"


async def _send_messenger_delivery_async(delivery_id: UUID) -> None:
    engine = build_engine(get_settings())
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def run() -> None:
        async with factory() as session:
            delivery = await session.scalar(
                select(ChannelOutboundDelivery)
                .where(ChannelOutboundDelivery.id == delivery_id)
                .with_for_update()
            )
            if not delivery or delivery.status in MESSENGER_TERMINAL_STATUSES:
                await session.rollback()
                return
            if delivery.provider != ChannelProvider.FACEBOOK_MESSENGER.value:
                delivery.status = "rejected"
                delivery.last_error = "Unsupported outbound provider"
                await session.commit()
                return
            if delivery.connection_id is None:
                delivery.status = "cancelled"
                delivery.last_error = "Facebook Messenger connection was disconnected"
                message = await session.get(Message, delivery.message_id)
                if message:
                    message.finish_reason = "cancelled"
                await session.commit()
                return

            delivery.status = "processing"
            delivery.attempt_count += 1
            delivery.last_error = None
            await session.commit()

            message = await session.get(Message, delivery.message_id)
            connection = await session.get(ChannelConnection, delivery.connection_id)
            if (
                not message
                or not connection
                or connection.tenant_id != delivery.tenant_id
                or connection.provider != ChannelProvider.FACEBOOK_MESSENGER.value
                or connection.status == "disabled"
            ):
                delivery.status = "cancelled"
                delivery.last_error = "Facebook Messenger connection or message is unavailable"
                if message:
                    message.finish_reason = "cancelled"
                await session.commit()
                return

            try:
                credentials = (
                    credential_store.decrypt(connection.credentials_encrypted)
                    if connection.credentials_encrypted
                    else {}
                )
            except CredentialStoreError:
                delivery.status = "reconnect_required"
                delivery.last_error = "Facebook Messenger credentials require reconnection"
                message.finish_reason = "failed"
                connection.status = "reconnect_required"
                connection.last_failure_at = datetime.now(UTC)
                connection.last_error = "Facebook Messenger credentials require reconnection"
                await session.commit()
                return

            page_access_token = str(credentials.get("page_access_token") or "")
            page_id = str((connection.configuration_json or {}).get("pageId") or "")
            api_version = normalize_messenger_api_version(
                (connection.configuration_json or {}).get("apiVersion")
            )
            if not page_access_token or not page_id:
                delivery.status = "reconnect_required"
                delivery.last_error = "Facebook Page access token or Page ID is not configured"
                message.finish_reason = "failed"
                connection.status = "reconnect_required"
                connection.last_failure_at = datetime.now(UTC)
                connection.last_error = "Facebook Messenger outbound credentials are incomplete"
                await session.commit()
                return

            sent_ids = list(delivery.provider_message_ids or [])
            chunks = split_messenger_text(message.content)
            if not chunks:
                delivery.status = "rejected"
                delivery.last_error = "Facebook Messenger message text is empty"
                message.finish_reason = "rejected"
                await session.commit()
                return
            for chunk in chunks[len(sent_ids) :]:
                provider_id = await messenger_client.send_text(
                    page_access_token,
                    page_id=page_id,
                    recipient_id=delivery.recipient_external_id,
                    text=chunk,
                    api_version=api_version,
                )
                sent_ids.append(provider_id)
                delivery.provider_message_ids = list(sent_ids)
                await session.commit()

            delivery.status = "sent"
            delivery.processed_at = datetime.now(UTC)
            delivery.next_dispatch_at = None
            delivery.last_error = None
            message.finish_reason = "sent"
            connection.last_error = None
            connection.last_health_at = datetime.now(UTC)
            if connection.status in {"configured", "failed", "reconnect_required", "configuration_error"}:
                connection.status = "healthy"
            await session.commit()

    try:
        if engine.dialect.name != "postgresql":
            await run()
        else:
            async with factory() as lookup_session:
                lock_delivery = await lookup_session.get(ChannelOutboundDelivery, delivery_id)
                if (
                    not lock_delivery
                    or lock_delivery.status in MESSENGER_TERMINAL_STATUSES
                    or lock_delivery.connection_id is None
                ):
                    return
                lock_key = messenger_thread_lock_key(
                    lock_delivery.connection_id,
                    lock_delivery.recipient_external_id,
                )
            async with engine.connect() as lock_connection:
                async with lock_connection.begin():
                    await lock_connection.execute(
                        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                        {"key": lock_key},
                    )
                    await run()
    except MessengerAPIError as exc:
        async with factory() as session:
            delivery = await session.get(ChannelOutboundDelivery, delivery_id)
            if delivery and delivery.status not in MESSENGER_TERMINAL_STATUSES:
                delivery.last_error = f"Facebook Messenger delivery failed: {exc}"[:1000]
                message = await session.get(Message, delivery.message_id)
                connection = (
                    await session.get(ChannelConnection, delivery.connection_id)
                    if delivery.connection_id is not None
                    else None
                )
                if exc.requires_reconnect:
                    delivery.status = "reconnect_required"
                    delivery.next_dispatch_at = None
                    if message:
                        message.finish_reason = "failed"
                    if connection:
                        connection.status = "reconnect_required"
                        connection.last_failure_at = datetime.now(UTC)
                        connection.last_error = "Facebook Messenger authorization failed"
                elif not exc.retryable:
                    delivery.status = "rejected"
                    delivery.next_dispatch_at = None
                    if message:
                        message.finish_reason = "rejected"
                    if connection:
                        connection.last_failure_at = datetime.now(UTC)
                        connection.last_error = "Facebook Messenger delivery was rejected"
                else:
                    delivery.status = "failed"
                    if message:
                        message.finish_reason = "queued"
                    if connection:
                        connection.last_failure_at = datetime.now(UTC)
                        connection.last_error = "Facebook Messenger delivery temporarily failed"
                await session.commit()
                if not exc.retryable:
                    return
        raise
    except Exception as exc:
        async with factory() as session:
            delivery = await session.get(ChannelOutboundDelivery, delivery_id)
            if delivery and delivery.status not in MESSENGER_TERMINAL_STATUSES:
                delivery.status = "failed"
                delivery.last_error = f"Facebook Messenger delivery failed: {type(exc).__name__}"[:1000]
                message = await session.get(Message, delivery.message_id)
                if message:
                    message.finish_reason = "queued"
                await session.commit()
        raise
    finally:
        await engine.dispose()


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="northstar.send_facebook_messenger_message",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=5,
)
def send_facebook_messenger_message(_task: object, delivery_id: str) -> None:
    asyncio.run(_send_messenger_delivery_async(UUID(delivery_id)))
