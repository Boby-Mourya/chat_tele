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
from northstar_api.services.slack import (
    SlackAPIError,
    decode_slack_target,
    slack_client,
    split_slack_text,
)
from northstar_api.workers.celery_app import celery_app

logger = structlog.get_logger(__name__)
SLACK_TERMINAL_STATUSES = frozenset(
    {"sent", "cancelled", "rejected", "reconnect_required", "dispatch_failed"}
)


def slack_thread_lock_key(connection_id: UUID, target: str) -> str:
    return f"slack-thread:{connection_id}:{target}"


async def _send_slack_delivery_async(delivery_id: UUID) -> None:
    engine = build_engine(get_settings())
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def run() -> None:
        async with factory() as session:
            delivery = await session.scalar(
                select(ChannelOutboundDelivery)
                .where(ChannelOutboundDelivery.id == delivery_id)
                .with_for_update()
            )
            if not delivery or delivery.status in SLACK_TERMINAL_STATUSES:
                await session.rollback()
                return
            if delivery.provider != ChannelProvider.SLACK.value:
                delivery.status = "rejected"
                delivery.last_error = "Unsupported outbound provider"
                await session.commit()
                return
            if delivery.connection_id is None:
                delivery.status = "cancelled"
                delivery.last_error = "Slack connection was disconnected"
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
                or connection.provider != ChannelProvider.SLACK.value
                or connection.status == "disabled"
            ):
                delivery.status = "cancelled"
                delivery.last_error = "Slack connection or message is unavailable"
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
                delivery.last_error = "Slack credentials require reconnection"
                message.finish_reason = "failed"
                connection.status = "reconnect_required"
                connection.last_failure_at = datetime.now(UTC)
                connection.last_error = "Slack credentials require reconnection"
                await session.commit()
                return

            bot_token = str(credentials.get("bot_token") or "")
            target = decode_slack_target(delivery.recipient_external_id)
            if not bot_token or target is None:
                delivery.status = "reconnect_required" if not bot_token else "rejected"
                delivery.last_error = (
                    "Slack bot token is not configured"
                    if not bot_token
                    else "Slack conversation target is invalid"
                )
                message.finish_reason = "failed" if not bot_token else "rejected"
                if not bot_token:
                    connection.status = "reconnect_required"
                    connection.last_failure_at = datetime.now(UTC)
                    connection.last_error = "Slack outbound credentials are incomplete"
                await session.commit()
                return

            channel_id, thread_ts = target
            sent_ids = list(delivery.provider_message_ids or [])
            chunks = split_slack_text(message.content)
            if not chunks:
                delivery.status = "rejected"
                delivery.last_error = "Slack message text is empty"
                message.finish_reason = "rejected"
                await session.commit()
                return

            remaining = chunks[len(sent_ids) :]
            for index, chunk in enumerate(remaining):
                provider_id = await slack_client.post_message(
                    bot_token,
                    channel_id=channel_id,
                    thread_ts=thread_ts,
                    text=chunk,
                )
                sent_ids.append(provider_id)
                delivery.provider_message_ids = list(sent_ids)
                await session.commit()
                # Slack recommends pacing message writes per conversation.
                if index < len(remaining) - 1:
                    await asyncio.sleep(1.0)

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
                    or lock_delivery.status in SLACK_TERMINAL_STATUSES
                    or lock_delivery.connection_id is None
                ):
                    return
                lock_key = slack_thread_lock_key(
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
    except SlackAPIError as exc:
        async with factory() as session:
            delivery = await session.get(ChannelOutboundDelivery, delivery_id)
            if delivery and delivery.status not in SLACK_TERMINAL_STATUSES:
                delivery.last_error = f"Slack delivery failed: {exc}"[:1000]
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
                        connection.last_error = "Slack authorization failed"
                elif not exc.retryable:
                    delivery.status = "rejected"
                    delivery.next_dispatch_at = None
                    if message:
                        message.finish_reason = "rejected"
                    if connection:
                        connection.last_failure_at = datetime.now(UTC)
                        connection.last_error = "Slack delivery was rejected"
                else:
                    delivery.status = "failed"
                    if message:
                        message.finish_reason = "queued"
                    if connection:
                        connection.last_failure_at = datetime.now(UTC)
                        connection.last_error = "Slack delivery temporarily failed"
                await session.commit()
                if not exc.retryable:
                    return
        raise
    except Exception as exc:
        async with factory() as session:
            delivery = await session.get(ChannelOutboundDelivery, delivery_id)
            if delivery and delivery.status not in SLACK_TERMINAL_STATUSES:
                delivery.status = "failed"
                delivery.last_error = f"Slack delivery failed: {type(exc).__name__}"[:1000]
                message = await session.get(Message, delivery.message_id)
                if message:
                    message.finish_reason = "queued"
                await session.commit()
        raise
    finally:
        await engine.dispose()


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="northstar.send_slack_message",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=5,
)
def send_slack_message(_task: object, delivery_id: str) -> None:
    asyncio.run(_send_slack_delivery_async(UUID(delivery_id)))
