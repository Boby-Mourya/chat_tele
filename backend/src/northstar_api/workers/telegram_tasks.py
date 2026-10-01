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
from northstar_api.services.telegram import TelegramAPIError, split_telegram_text, telegram_client
from northstar_api.workers.celery_app import celery_app

logger = structlog.get_logger(__name__)
TELEGRAM_TERMINAL_STATUSES = frozenset(
    {"sent", "cancelled", "rejected", "reconnect_required", "dispatch_failed"}
)


def telegram_thread_lock_key(connection_id: UUID, chat_id: str) -> str:
    return f"telegram-thread:{connection_id}:{chat_id}"


async def _send_telegram_delivery_async(delivery_id: UUID) -> None:
    engine = build_engine(get_settings())
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def run() -> None:
        async with factory() as session:
            delivery = await session.scalar(
                select(ChannelOutboundDelivery)
                .where(ChannelOutboundDelivery.id == delivery_id)
                .with_for_update()
            )
            if not delivery or delivery.status in TELEGRAM_TERMINAL_STATUSES:
                await session.rollback()
                return
            if delivery.provider != ChannelProvider.TELEGRAM.value:
                delivery.status = "rejected"
                delivery.last_error = "Unsupported outbound provider"
                await session.commit()
                return
            if delivery.connection_id is None:
                delivery.status = "cancelled"
                delivery.last_error = "Telegram connection was disconnected"
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
                or connection.provider != ChannelProvider.TELEGRAM.value
                or connection.status == "disabled"
            ):
                delivery.status = "cancelled"
                delivery.last_error = "Telegram connection or message is unavailable"
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
                delivery.last_error = "Telegram credentials require reconnection"
                message.finish_reason = "failed"
                connection.status = "reconnect_required"
                connection.last_failure_at = datetime.now(UTC)
                connection.last_error = "Telegram credentials require reconnection"
                await session.commit()
                return

            bot_token = str(credentials.get("bot_token") or "")
            if not bot_token:
                delivery.status = "reconnect_required"
                delivery.last_error = "Telegram bot token is not configured"
                message.finish_reason = "failed"
                connection.status = "reconnect_required"
                connection.last_failure_at = datetime.now(UTC)
                connection.last_error = "Telegram bot token is not configured"
                await session.commit()
                return

            sent_ids = list(delivery.provider_message_ids or [])
            chunks = split_telegram_text(message.content)
            if not chunks:
                delivery.status = "rejected"
                delivery.last_error = "Telegram message text is empty"
                message.finish_reason = "rejected"
                await session.commit()
                return
            for chunk in chunks[len(sent_ids) :]:
                provider_id = await telegram_client.send_text(
                    bot_token,
                    chat_id=delivery.recipient_external_id,
                    text=chunk,
                    **({"reply_markup": delivery.reply_markup} if delivery.reply_markup else {}),
                )
                sent_ids.append(provider_id)
                delivery.provider_message_ids = list(sent_ids)
                await session.commit()

            delivery.status = "sent"
            delivery.processed_at = datetime.now(UTC)
            delivery.next_dispatch_at = None
            delivery.last_error = None
            message.finish_reason = "sent"
            await session.refresh(connection, with_for_update=True)
            if connection.status == "disabled":
                await session.commit()
                return
            connection.last_error = None
            connection.last_health_at = datetime.now(UTC)
            if not (connection.configuration_json or {}).get("telegram", {}).get("managed") and connection.status in {"configured", "failed", "reconnect_required", "configuration_error"}:
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
                    or lock_delivery.status in TELEGRAM_TERMINAL_STATUSES
                    or lock_delivery.connection_id is None
                ):
                    return
                lock_key = telegram_thread_lock_key(
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
    except TelegramAPIError as exc:
        async with factory() as session:
            delivery = await session.get(ChannelOutboundDelivery, delivery_id)
            if delivery and delivery.status not in TELEGRAM_TERMINAL_STATUSES:
                delivery.last_error = f"Telegram delivery failed: {exc}"[:1000]
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
                    if connection and connection.status != "disabled":
                        connection.status = "reconnect_required"
                        connection.last_failure_at = datetime.now(UTC)
                        connection.last_error = "Telegram authorization failed"
                elif not exc.retryable:
                    delivery.status = "rejected"
                    delivery.next_dispatch_at = None
                    if message:
                        message.finish_reason = "rejected"
                    if connection:
                        connection.last_failure_at = datetime.now(UTC)
                        connection.last_error = "Telegram delivery was rejected"
                else:
                    delivery.status = "failed"
                    if message:
                        message.finish_reason = "queued"
                    if connection:
                        connection.last_failure_at = datetime.now(UTC)
                        connection.last_error = "Telegram delivery temporarily failed"
                await session.commit()
                if not exc.retryable:
                    return
        raise
    except Exception as exc:
        async with factory() as session:
            delivery = await session.get(ChannelOutboundDelivery, delivery_id)
            if delivery and delivery.status not in TELEGRAM_TERMINAL_STATUSES:
                delivery.status = "failed"
                delivery.last_error = f"Telegram delivery failed: {type(exc).__name__}"[:1000]
                message = await session.get(Message, delivery.message_id)
                if message:
                    message.finish_reason = "queued"
                await session.commit()
        raise
    finally:
        await engine.dispose()


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="northstar.send_telegram_message",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=5,
)
def send_telegram_message(_task: object, delivery_id: str) -> None:
    asyncio.run(_send_telegram_delivery_async(UUID(delivery_id)))
