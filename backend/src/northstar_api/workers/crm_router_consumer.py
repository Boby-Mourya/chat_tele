from __future__ import annotations

import asyncio
import signal
from datetime import datetime
from uuid import UUID

import structlog
from aiokafka import AIOKafkaConsumer  # type: ignore[import-untyped]
from aiokafka.structs import TopicPartition  # type: ignore[import-untyped]
from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from northstar_api.config import get_settings
from northstar_api.database import build_engine
from northstar_api.lead_crm.workspace_routing import workspace_crm_route_service
from northstar_api.logging import configure_logging
from northstar_api.models import Lead, ProcessedEvent
from northstar_api.services.entitlements import EntitlementError, require_feature
from northstar_api.services.outbox import enqueue_event
from northstar_api.workers.event_utils import EventEnvelope, parse_envelope, quarantine_event

settings = get_settings()
configure_logging(settings)
logger = structlog.get_logger(__name__)
CONSUMER_NAME = "crm-router-v1"
LEAD_SYNC_TOPIC = "lead.crm.sync.requested.v1"
BACKFILL_TOPIC = "crm.connection.backfill.requested.v1"
TOPICS = [LEAD_SYNC_TOPIC, BACKFILL_TOPIC]


def _uuid_value(payload: dict[str, object], key: str, *, label: str) -> UUID:
    try:
        return UUID(str(payload[key]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"CRM event has no valid {label}") from exc


def _optional_uuid(payload: dict[str, object], key: str, *, label: str) -> UUID | None:
    value = payload.get(key)
    if value in (None, ""):
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"CRM event has invalid {label}") from exc


def _origin_connection_id(payload: dict[str, object]) -> UUID | None:
    return _optional_uuid(payload, "originConnectionId", label="originConnectionId")


def _sync_reason(payload: dict[str, object]) -> str | None:
    value = payload.get("reason")
    return str(value) if value is not None else None


def _batch_size(payload: dict[str, object]) -> int:
    raw = payload.get("batchSize") or 100
    if not isinstance(raw, (str, int, float)):
        raise ValueError("CRM backfill event has an invalid batchSize")
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("CRM backfill event has an invalid batchSize") from exc
    return max(1, min(value, 500))


def _cursor(payload: dict[str, object]) -> tuple[datetime, UUID] | None:
    created_at = payload.get("afterCreatedAt")
    lead_id = payload.get("afterLeadId")
    if created_at in (None, "") and lead_id in (None, ""):
        return None
    if created_at in (None, "") or lead_id in (None, ""):
        raise ValueError("CRM backfill cursor is incomplete")
    try:
        return datetime.fromisoformat(str(created_at)), UUID(str(lead_id))
    except (TypeError, ValueError) as exc:
        raise ValueError("CRM backfill cursor is invalid") from exc


async def _route_lead_event(session: AsyncSession, event: EventEnvelope) -> dict[str, object]:
    lead_id = _uuid_value(event.payload, "leadId", label="leadId")
    sync_reason = _sync_reason(event.payload)
    origin_connection_id = _optional_uuid(
        event.payload,
        "originConnectionId",
        label="originConnectionId",
    )
    deliveries = await workspace_crm_route_service.create_deliveries(
        session,
        tenant_id=event.tenant_id,
        lead_id=lead_id,
        correlation_id=str(event.event_id),
        sync_reason=sync_reason,
        origin_connection_id=origin_connection_id,
    )
    return {
        "mode": "lead",
        "lead_id": lead_id,
        "sync_reason": sync_reason,
        "origin_connection_id": origin_connection_id,
        "delivery_count": len(deliveries),
    }


async def _route_backfill_event(
    session: AsyncSession,
    event: EventEnvelope,
) -> dict[str, object]:
    workspace_id = _uuid_value(event.payload, "workspaceId", label="workspaceId")
    connection_id = _uuid_value(event.payload, "connectionId", label="connectionId")
    batch_size = _batch_size(event.payload)
    cursor = _cursor(event.payload)
    conditions = [
        Lead.tenant_id == event.tenant_id,
        Lead.workspace_id == workspace_id,
        Lead.status.notin_(("archived", "lost")),
    ]
    if cursor is not None:
        created_at, lead_id = cursor
        conditions.append(
            or_(
                Lead.created_at > created_at,
                and_(Lead.created_at == created_at, Lead.id > lead_id),
            )
        )
    candidates = list(
        await session.scalars(
            select(Lead).where(*conditions).order_by(Lead.created_at, Lead.id).limit(batch_size + 1)
        )
    )
    batch = candidates[:batch_size]
    delivery_count = 0
    for lead in batch:
        deliveries = await workspace_crm_route_service.create_deliveries(
            session,
            tenant_id=event.tenant_id,
            lead_id=lead.id,
            correlation_id=str(event.event_id),
            sync_reason="manual",
            target_connection_id=connection_id,
        )
        delivery_count += len(deliveries)

    has_more = len(candidates) > batch_size
    if has_more and batch:
        last = batch[-1]
        enqueue_event(
            session,
            tenant_id=event.tenant_id,
            aggregate_type="crm_connection",
            aggregate_id=connection_id,
            event_type=BACKFILL_TOPIC,
            payload={
                "workspaceId": str(workspace_id),
                "connectionId": str(connection_id),
                "batchSize": batch_size,
                "afterCreatedAt": last.created_at.isoformat(),
                "afterLeadId": str(last.id),
            },
        )
    return {
        "mode": "backfill",
        "workspace_id": workspace_id,
        "connection_id": connection_id,
        "lead_count": len(batch),
        "delivery_count": delivery_count,
        "has_more": has_more,
    }


async def _route_event(session: AsyncSession, event: EventEnvelope) -> dict[str, object]:
    if event.event_type == LEAD_SYNC_TOPIC:
        return await _route_lead_event(session, event)
    if event.event_type == BACKFILL_TOPIC:
        return await _route_backfill_event(session, event)
    raise ValueError("unsupported CRM router event type")


async def consume_forever() -> None:
    engine = build_engine(settings)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    consumer = AIOKafkaConsumer(
        *TOPICS,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=CONSUMER_NAME,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
        client_id="northstar-crm-router",
    )
    await consumer.start()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signal_name, stop.set)
        except NotImplementedError:
            pass
    logger.info("crm_router_consumer_started", topics=TOPICS)
    try:
        while not stop.is_set():
            batch = await consumer.getmany(timeout_ms=1000, max_records=10)
            for messages in batch.values():
                for message in messages:
                    topic_partition = TopicPartition(message.topic, message.partition)
                    raw = message.value if isinstance(message.value, bytes) else b""
                    try:
                        event = parse_envelope(raw)
                        if event.event_type != message.topic or event.event_type not in TOPICS:
                            raise ValueError("event type does not match a CRM router topic")
                        if event.event_type == LEAD_SYNC_TOPIC:
                            _uuid_value(event.payload, "leadId", label="leadId")
                            _optional_uuid(
                                event.payload,
                                "originConnectionId",
                                label="originConnectionId",
                            )
                        else:
                            _uuid_value(event.payload, "workspaceId", label="workspaceId")
                            _uuid_value(event.payload, "connectionId", label="connectionId")
                            _batch_size(event.payload)
                            _cursor(event.payload)
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
                    try:
                        async with factory() as session:
                            inserted = await session.scalar(
                                pg_insert(ProcessedEvent)
                                .values(event_id=event.event_id, consumer=CONSUMER_NAME)
                                .on_conflict_do_nothing(
                                    index_elements=[ProcessedEvent.event_id, ProcessedEvent.consumer]
                                )
                                .returning(ProcessedEvent.event_id)
                            )
                            if inserted is not None:
                                try:
                                    await require_feature(
                                        session,
                                        tenant_id=event.tenant_id,
                                        feature="crm",
                                    )
                                except EntitlementError as exc:
                                    await session.commit()
                                    logger.info(
                                        "crm_route_entitlement_skipped",
                                        event_id=str(event.event_id),
                                        tenant_id=str(event.tenant_id),
                                        topic=event.event_type,
                                        code=exc.code,
                                    )
                                else:
                                    result = await _route_event(session, event)
                                    await session.commit()
                                    logger.info(
                                        "crm_routes_evaluated",
                                        event_id=str(event.event_id),
                                        tenant_id=str(event.tenant_id),
                                        topic=event.event_type,
                                        **result,
                                    )
                            else:
                                await session.commit()
                        await consumer.commit({topic_partition: message.offset + 1})
                    except Exception as exc:
                        logger.warning(
                            "crm_router_retry",
                            event_id=str(event.event_id),
                            topic=event.event_type,
                            error=type(exc).__name__,
                        )
                        consumer.seek(topic_partition, message.offset)
                        try:
                            await asyncio.wait_for(stop.wait(), timeout=1.0)
                        except TimeoutError:
                            pass
                        break
    finally:
        await consumer.stop()
        await engine.dispose()
        logger.info("crm_router_consumer_stopped")


def main() -> None:
    if not settings.kafka_enabled:
        raise SystemExit("KAFKA_ENABLED must be true for the CRM router consumer")
    asyncio.run(consume_forever())


if __name__ == "__main__":
    main()
