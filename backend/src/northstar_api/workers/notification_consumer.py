from __future__ import annotations

import asyncio
import signal

import structlog
from aiokafka import AIOKafkaConsumer  # type: ignore[import-untyped]
from aiokafka.structs import TopicPartition  # type: ignore[import-untyped]
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from northstar_api.config import get_settings
from northstar_api.database import build_engine, set_tenant_context, tenant_context
from northstar_api.logging import configure_logging
from northstar_api.models import ProcessedEvent
from northstar_api.services.notifications import project_notification_event
from northstar_api.workers.event_utils import parse_envelope, quarantine_event

settings = get_settings()
configure_logging(settings)
logger = structlog.get_logger(__name__)
CONSUMER_NAME = "notifications-v1"
TOPICS = [
    "lead.created.v1",
    "lead.crm.delivery.failed.v1",
    "education.conversation.resolution.context_missing.v1",
]


async def consume_forever() -> None:
    engine = build_engine(settings)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    consumer = AIOKafkaConsumer(
        *TOPICS,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=CONSUMER_NAME,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
        client_id="northstar-notifications",
    )
    await consumer.start()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signal_name, stop.set)
        except NotImplementedError:
            pass
    logger.info("notification_consumer_started")
    try:
        while not stop.is_set():
            batch = await consumer.getmany(timeout_ms=1000, max_records=50)
            for messages in batch.values():
                for message in messages:
                    topic_partition = TopicPartition(message.topic, message.partition)
                    raw = message.value if isinstance(message.value, bytes) else b""
                    try:
                        event = parse_envelope(raw)
                        if event.event_type != message.topic:
                            raise ValueError("event type does not match Kafka topic")
                    except ValueError as exc:
                        async with factory() as session:
                            await quarantine_event(
                                session,
                                consumer=CONSUMER_NAME,
                                topic=message.topic,
                                partition=message.partition,
                                offset=message.offset,
                                raw=raw,
                                error=exc,
                            )
                        await consumer.commit({topic_partition: message.offset + 1})
                        continue

                    context_token = tenant_context.set(None)
                    try:
                        async with factory() as session:
                            await set_tenant_context(session, event.tenant_id)
                            inserted = await session.scalar(
                                pg_insert(ProcessedEvent)
                                .values(event_id=event.event_id, consumer=CONSUMER_NAME)
                                .on_conflict_do_nothing(
                                    index_elements=[ProcessedEvent.event_id, ProcessedEvent.consumer]
                                )
                                .returning(ProcessedEvent.event_id)
                            )
                            created = 0
                            if inserted is not None:
                                created = await project_notification_event(
                                    session,
                                    event_id=event.event_id,
                                    event_type=event.event_type,
                                    tenant_id=event.tenant_id,
                                    payload=event.payload,
                                )
                            await session.commit()
                        await consumer.commit({topic_partition: message.offset + 1})
                        logger.info(
                            "notification_event_processed",
                            event_id=str(event.event_id),
                            event_type=event.event_type,
                            created=created,
                        )
                    except Exception as exc:
                        logger.warning(
                            "notification_event_retry",
                            event_id=str(event.event_id),
                            event_type=event.event_type,
                            error=type(exc).__name__,
                        )
                        consumer.seek(topic_partition, message.offset)
                        try:
                            await asyncio.wait_for(stop.wait(), timeout=1.0)
                        except TimeoutError:
                            pass
                        break
                    finally:
                        tenant_context.reset(context_token)
    finally:
        await consumer.stop()
        await engine.dispose()
        logger.info("notification_consumer_stopped")


def main() -> None:
    if not settings.kafka_enabled:
        raise SystemExit("KAFKA_ENABLED must be true for the notification consumer")
    asyncio.run(consume_forever())


if __name__ == "__main__":
    main()
