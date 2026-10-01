from __future__ import annotations

import asyncio
import json
import secrets
import signal
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from northstar_api.config import get_settings
from northstar_api.database import build_engine
from northstar_api.lead_crm.circuit import allow_request, record_failure, record_success
from northstar_api.lead_crm.connection_context import load_connection_context
from northstar_api.lead_crm.connectors import CRMConnectionContext, CRMError, crm_registry
from northstar_api.lead_crm.domain import (
    CRMConnectionStatus,
    CRMDeliveryStatus,
    CRMOperation,
    CRMProvider,
    NormalizedCRMErrorCode,
)
from northstar_api.lead_crm.mapping import build_mapped_payload
from northstar_api.lead_crm.models import (
    CRMConnection,
    CRMDelivery,
    CRMDeliveryAttempt,
    CRMExternalReference,
    CRMFieldMapping,
    IntegrationDeadLetter,
    LeadActivityEvent,
    LeadProfile,
)
from northstar_api.lead_crm.verification import as_utc, verification_failed, verify_delivery
from northstar_api.logging import configure_logging
from northstar_api.models import Lead
from northstar_api.services.education_conversation_policy import is_education_lead
from northstar_api.services.outbox import enqueue_event

settings = get_settings()
configure_logging(settings)
logger = structlog.get_logger(__name__)


def _retry_delay(attempt: int, retry_after: int | None = None) -> int:
    if retry_after is not None:
        return min(max(retry_after, 1), 3600)
    base = min(900, 2 ** min(max(attempt, 1), 9))
    jitter_max = max(1, min(10, int(base * 0.2)))
    return int(max(1, base + secrets.randbelow(jitter_max + 1)))


def _max_attempts(connection: CRMConnection) -> int:
    raw = (connection.configuration_json or {}).get("maxAttempts", 5)
    try:
        return min(max(int(raw), 1), 20)
    except (TypeError, ValueError):
        return 5


def _circuit_threshold(connection: CRMConnection) -> int:
    raw = (connection.configuration_json or {}).get("circuitFailureThreshold", 5)
    try:
        return min(max(int(raw), 2), 50)
    except (TypeError, ValueError):
        return 5


def _circuit_cooldown(connection: CRMConnection) -> int:
    raw = (connection.configuration_json or {}).get("circuitCooldownSeconds", 60)
    try:
        return min(max(int(raw), 5), 3600)
    except (TypeError, ValueError):
        return 60


async def _context(
    session: AsyncSession, delivery: CRMDelivery
) -> tuple[CRMConnection, CRMConnectionContext]:
    return await load_connection_context(
        session, tenant_id=delivery.tenant_id, connection_id=delivery.connection_id
    )


async def _mark_failure(
    session: AsyncSession,
    delivery: CRMDelivery,
    connection: CRMConnection | None,
    error: CRMError,
) -> None:
    if delivery.acknowledged_at is not None:
        await verification_failed(session, delivery, connection, error)
        return
    delivery.last_error_code = error.code.value
    delivery.last_error_message = str(error)[:1000]
    delivery.provider_http_status = error.http_status
    delivery.provider_code = error.provider_code
    now = datetime.now(UTC)
    if connection:
        connection.last_failure_at = now
        connection.last_error = error.code.value
        if error.retryable or error.code == NormalizedCRMErrorCode.RATE_LIMIT_ERROR:
            await record_failure(
                session,
                tenant_id=delivery.tenant_id,
                connection_id=connection.id,
                threshold=_circuit_threshold(connection),
                cooldown_seconds=_circuit_cooldown(connection),
            )

    if error.requires_reconnect:
        delivery.status = CRMDeliveryStatus.AUTH_REQUIRED.value
        delivery.next_retry_at = None
        if connection:
            connection.status = CRMConnectionStatus.AUTH_REQUIRED.value
    elif error.code == NormalizedCRMErrorCode.MAPPING_ERROR:
        delivery.status = CRMDeliveryStatus.MAPPING_ERROR.value
        delivery.next_retry_at = None
        if connection:
            connection.status = CRMConnectionStatus.DEGRADED.value
    elif error.code == NormalizedCRMErrorCode.RATE_LIMIT_ERROR:
        if delivery.retry_cycle_attempts >= (_max_attempts(connection) if connection else 5):
            delivery.status = CRMDeliveryStatus.DEAD_LETTER.value
            delivery.next_retry_at = None
        else:
            delivery.status = CRMDeliveryStatus.RATE_LIMITED.value
            delivery.next_retry_at = now + timedelta(
                seconds=_retry_delay(delivery.attempt_count, error.retry_after_seconds)
            )
            if connection:
                connection.status = CRMConnectionStatus.RATE_LIMITED.value
    elif error.retryable:
        if delivery.retry_cycle_attempts >= (_max_attempts(connection) if connection else 5):
            delivery.status = CRMDeliveryStatus.DEAD_LETTER.value
            delivery.next_retry_at = None
        else:
            delivery.status = CRMDeliveryStatus.RETRYING.value
            delivery.next_retry_at = now + timedelta(seconds=_retry_delay(delivery.attempt_count))
    else:
        delivery.status = CRMDeliveryStatus.FAILED.value
        delivery.next_retry_at = None

    if delivery.status == CRMDeliveryStatus.DEAD_LETTER.value:
        existing = await session.scalar(
            select(IntegrationDeadLetter.id).where(
                IntegrationDeadLetter.tenant_id == delivery.tenant_id,
                IntegrationDeadLetter.delivery_id == delivery.id,
                IntegrationDeadLetter.status == "open",
            )
        )
        if existing is None:
            session.add(
                IntegrationDeadLetter(
                    tenant_id=delivery.tenant_id,
                    delivery_id=delivery.id,
                    reason_code=error.code.value,
                    reason_message=str(error)[:1000],
                    metadata_json={"providerCode": error.provider_code, "httpStatus": error.http_status},
                )
            )
    session.add(
        LeadActivityEvent(
            tenant_id=delivery.tenant_id,
            lead_id=delivery.lead_id,
            event_type="lead.crm.delivery.failed.v1",
            correlation_id=delivery.correlation_id,
            details_json={
                "deliveryId": str(delivery.id),
                "provider": delivery.provider,
                "status": delivery.status,
                "errorCode": error.code.value,
            },
        )
    )
    enqueue_event(
        session,
        tenant_id=delivery.tenant_id,
        aggregate_type="crm_delivery",
        aggregate_id=delivery.id,
        event_type="lead.crm.delivery.failed.v1",
        payload={
            "leadId": str(delivery.lead_id),
            "deliveryId": str(delivery.id),
            "provider": delivery.provider,
            "status": delivery.status,
            "errorCode": error.code.value,
        },
    )


async def process_delivery(session: AsyncSession, delivery_id: UUID) -> None:
    delivery = await session.scalar(
        select(CRMDelivery).where(CRMDelivery.id == delivery_id).with_for_update()
    )
    if delivery is not None and delivery.acknowledged_at is not None:
        if delivery.status != CRMDeliveryStatus.VERIFIED.value:
            delivery.status = CRMDeliveryStatus.ACKNOWLEDGED.value
            await verify_delivery(session, delivery)
            await session.commit()
        return
    if not delivery or delivery.status not in {
        CRMDeliveryStatus.QUEUED.value,
        CRMDeliveryStatus.RETRYING.value,
        CRMDeliveryStatus.RATE_LIMITED.value,
    }:
        return
    if delivery.next_retry_at and as_utc(delivery.next_retry_at) > datetime.now(UTC):
        return
    if await is_education_lead(session, delivery.lead_id):
        delivery.status = CRMDeliveryStatus.CANCELLED.value
        delivery.next_retry_at = None
        delivery.last_error_code = "education_conversation"
        delivery.last_error_message = "Education chats do not enter the lead or CRM workflow"
        await session.commit()
        return
    connection = await session.scalar(
        select(CRMConnection).where(
            CRMConnection.id == delivery.connection_id,
            CRMConnection.tenant_id == delivery.tenant_id,
        )
    )
    if connection is None:
        return
    if not await allow_request(
        session,
        tenant_id=delivery.tenant_id,
        connection_id=delivery.connection_id,
    ):
        delivery.status = CRMDeliveryStatus.RETRYING.value
        delivery.next_retry_at = datetime.now(UTC) + timedelta(seconds=_circuit_cooldown(connection))
        delivery.last_error_code = "circuit_open"
        delivery.last_error_message = "CRM connection circuit breaker is open"
        await session.commit()
        return

    delivery.status = CRMDeliveryStatus.PROCESSING.value
    delivery.processing_at = datetime.now(UTC)
    delivery.attempt_count += 1
    delivery.retry_cycle_attempts += 1
    attempt = CRMDeliveryAttempt(
        tenant_id=delivery.tenant_id,
        delivery_id=delivery.id,
        attempt_number=delivery.attempt_count,
    )
    session.add(attempt)
    await session.commit()

    connection = None
    provider_accepted = False
    started = time.monotonic()
    try:
        delivery = await session.scalar(
            select(CRMDelivery).where(CRMDelivery.id == delivery_id).with_for_update()
        )
        if not delivery:
            return
        connection, context = await _context(session, delivery)
        lead = await session.scalar(
            select(Lead).where(Lead.id == delivery.lead_id, Lead.tenant_id == delivery.tenant_id)
        )
        profile = await session.scalar(
            select(LeadProfile).where(
                LeadProfile.tenant_id == delivery.tenant_id,
                LeadProfile.lead_id == delivery.lead_id,
            )
        )
        if not lead or not profile:
            raise CRMError(
                NormalizedCRMErrorCode.CONFIGURATION_ERROR, "Lead canonical profile is unavailable"
            )
        mapping = await session.scalar(
            select(CRMFieldMapping).where(
                CRMFieldMapping.tenant_id == delivery.tenant_id,
                CRMFieldMapping.connection_id == delivery.connection_id,
                CRMFieldMapping.object_name == "Leads",
            )
        )
        if mapping is not None and mapping.status != "active":
            raise CRMError(
                NormalizedCRMErrorCode.MAPPING_ERROR,
                "CRM mapping must be validated against the current schema before delivery",
            )
        payload = dict(delivery.payload_json or {})
        if not payload:
            payload = build_mapped_payload(
                lead,
                profile,
                mapping.mapping_json if mapping else None,
                provider=delivery.provider,
                configuration=connection.configuration_json,
            )
            if not payload:
                raise CRMError(NormalizedCRMErrorCode.MAPPING_ERROR, "CRM mapping produced an empty payload")
            delivery.payload_json = json.loads(json.dumps(payload))
            delivery.mapping_version = mapping.version if mapping else 0
        connector = crm_registry.get(CRMProvider(delivery.provider))
        reference = await session.scalar(
            select(CRMExternalReference).where(
                CRMExternalReference.tenant_id == delivery.tenant_id,
                CRMExternalReference.lead_id == delivery.lead_id,
                CRMExternalReference.connection_id == delivery.connection_id,
                CRMExternalReference.object_name == "Leads",
            )
        )
        if reference and delivery.operation == CRMOperation.UPSERT.value and connector.capabilities.update:
            delivery.operation = CRMOperation.UPDATE.value
            delivery.external_record_id = reference.external_id
        await session.commit()
        delivery = await session.scalar(
            select(CRMDelivery).where(CRMDelivery.id == delivery_id).with_for_update()
        )
        if delivery is None or delivery.status != CRMDeliveryStatus.PROCESSING.value:
            return
        connection, context = await _context(session, delivery)
        if delivery.operation == CRMOperation.CREATE.value:
            result = await connector.create_lead(context, payload, idempotency_key=delivery.idempotency_key)
        elif delivery.operation == CRMOperation.UPDATE.value:
            if not delivery.external_record_id:
                raise CRMError(
                    NormalizedCRMErrorCode.CONFIGURATION_ERROR,
                    "Update delivery has no external record ID",
                )
            result = await connector.update_lead(
                context,
                delivery.external_record_id,
                payload,
                idempotency_key=delivery.idempotency_key,
            )
        else:
            result = await connector.upsert_lead(context, payload, idempotency_key=delivery.idempotency_key)
        if not result.accepted:
            raise CRMError(NormalizedCRMErrorCode.UNKNOWN_ERROR, "CRM did not acknowledge delivery")

        provider_accepted = True
        now = datetime.now(UTC)
        delivery.status = CRMDeliveryStatus.ACKNOWLEDGED.value
        delivery.sent_at = delivery.sent_at or now
        delivery.acknowledged_at = now
        delivery.verification_status = "pending"
        delivery.external_record_id = result.external_record_id or delivery.external_record_id
        delivery.provider_http_status = result.http_status
        delivery.provider_code = result.provider_code
        delivery.provider_request_id = result.provider_request_id
        delivery.last_error_code = None
        delivery.last_error_message = None
        delivery.next_retry_at = None
        connection.last_success_at = now
        connection.last_error = None
        if connection.status != CRMConnectionStatus.DISABLED.value:
            connection.status = CRMConnectionStatus.HEALTHY.value
        await record_success(
            session,
            tenant_id=delivery.tenant_id,
            connection_id=connection.id,
        )
        stored_attempt = await session.scalar(
            select(CRMDeliveryAttempt).where(
                CRMDeliveryAttempt.delivery_id == delivery.id,
                CRMDeliveryAttempt.attempt_number == delivery.attempt_count,
            )
        )
        if stored_attempt:
            stored_attempt.finished_at = now
            stored_attempt.http_status = result.http_status
            stored_attempt.latency_ms = int((time.monotonic() - started) * 1000)
            stored_attempt.result_status = "acknowledged"
            stored_attempt.provider_request_id = result.provider_request_id

        if delivery.external_record_id:
            reference = await session.scalar(
                select(CRMExternalReference).where(
                    CRMExternalReference.tenant_id == delivery.tenant_id,
                    CRMExternalReference.lead_id == delivery.lead_id,
                    CRMExternalReference.connection_id == delivery.connection_id,
                    CRMExternalReference.object_name == "Leads",
                )
            )
            if reference is None:
                reference = CRMExternalReference(
                    tenant_id=delivery.tenant_id,
                    lead_id=delivery.lead_id,
                    connection_id=delivery.connection_id,
                    provider=delivery.provider,
                    object_name="Leads",
                    external_id=delivery.external_record_id,
                )
                session.add(reference)
            else:
                reference.external_id = delivery.external_record_id
                reference.sync_version += 1
                reference.change_origin = "platform"

        session.add(
            LeadActivityEvent(
                tenant_id=delivery.tenant_id,
                lead_id=delivery.lead_id,
                event_type="lead.crm.delivery.acknowledged.v1",
                correlation_id=delivery.correlation_id,
                details_json={
                    "deliveryId": str(delivery.id),
                    "provider": delivery.provider,
                    "externalRecordId": delivery.external_record_id,
                },
            )
        )
        enqueue_event(
            session,
            tenant_id=delivery.tenant_id,
            aggregate_type="crm_delivery",
            aggregate_id=delivery.id,
            event_type="lead.crm.delivery.acknowledged.v1",
            payload={
                "leadId": str(delivery.lead_id),
                "deliveryId": str(delivery.id),
                "externalRecordId": delivery.external_record_id,
                "provider": delivery.provider,
            },
        )
        await session.commit()

        delivery = await session.scalar(
            select(CRMDelivery).where(CRMDelivery.id == delivery_id).with_for_update()
        )
        if delivery is not None:
            await verify_delivery(session, delivery)
            await session.commit()
    except CRMError as exc:
        delivery = await session.scalar(
            select(CRMDelivery).where(CRMDelivery.id == delivery_id).with_for_update()
        )
        if not delivery:
            return
        if connection is None:
            connection = await session.scalar(
                select(CRMConnection).where(
                    CRMConnection.id == delivery.connection_id,
                    CRMConnection.tenant_id == delivery.tenant_id,
                )
            )
        stored_attempt = await session.scalar(
            select(CRMDeliveryAttempt).where(
                CRMDeliveryAttempt.delivery_id == delivery.id,
                CRMDeliveryAttempt.attempt_number == delivery.attempt_count,
            )
        )
        if stored_attempt and delivery.acknowledged_at is None:
            stored_attempt.finished_at = datetime.now(UTC)
            stored_attempt.http_status = exc.http_status
            stored_attempt.latency_ms = int((time.monotonic() - started) * 1000)
            stored_attempt.result_status = "failed"
            stored_attempt.normalized_error_code = exc.code.value
            stored_attempt.provider_error_code = exc.provider_code
        await _mark_failure(session, delivery, connection, exc)
        await session.commit()
    except Exception as exc:
        logger.error(
            "crm_delivery_unexpected_failure", delivery_id=str(delivery_id), error=type(exc).__name__
        )
        await session.rollback()
        delivery = await session.scalar(
            select(CRMDelivery).where(CRMDelivery.id == delivery_id).with_for_update()
        )
        if delivery is not None:
            connection = await session.scalar(
                select(CRMConnection).where(
                    CRMConnection.id == delivery.connection_id, CRMConnection.tenant_id == delivery.tenant_id
                )
            )
            if provider_accepted and delivery.acknowledged_at is None:
                delivery.status = CRMDeliveryStatus.FAILED.value
                delivery.last_error_code = "ambiguous_provider_ack"
                delivery.last_error_message = "Provider accepted before local commit failed; reconcile the remote record before retrying"
                delivery.next_retry_at = None
            else:
                await _mark_failure(
                    session,
                    delivery,
                    connection,
                    CRMError(
                        NormalizedCRMErrorCode.UNKNOWN_ERROR,
                        "Unexpected CRM delivery failure",
                        retryable=True,
                    ),
                )
            await session.commit()


async def run_forever() -> None:
    engine = build_engine(settings)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signal_name, stop.set)
        except NotImplementedError:
            pass
    logger.info("crm_delivery_worker_started")
    try:
        while not stop.is_set():
            now = datetime.now(UTC)
            async with factory() as session:
                rows = list(
                    await session.scalars(
                        select(CRMDelivery)
                        .where(
                            CRMDelivery.status.in_(("queued", "retrying", "rate_limited")),
                            or_(CRMDelivery.next_retry_at.is_(None), CRMDelivery.next_retry_at <= now),
                        )
                        .order_by(CRMDelivery.created_at)
                        .with_for_update(skip_locked=True)
                        .limit(20)
                    )
                )
                ids = [row.id for row in rows]
                await session.commit()
            if not ids:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=1.0)
                except TimeoutError:
                    pass
                continue
            for delivery_id in ids:
                async with factory() as session:
                    await process_delivery(session, delivery_id)
    finally:
        await engine.dispose()
        logger.info("crm_delivery_worker_stopped")


def main() -> None:
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
