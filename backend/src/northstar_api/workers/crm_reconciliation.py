from __future__ import annotations

import asyncio
import signal
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from northstar_api.config import get_settings
from northstar_api.database import build_engine
from northstar_api.lead_crm.connectors import CRMError
from northstar_api.lead_crm.domain import CRMDeliveryStatus, NormalizedCRMErrorCode
from northstar_api.lead_crm.models import CRMConnection, CRMDelivery, CRMDeliveryAttempt, LeadActivityEvent
from northstar_api.lead_crm.verification import verify_delivery
from northstar_api.logging import configure_logging
from northstar_api.workers.crm_delivery_worker import _mark_failure

settings = get_settings()
configure_logging(settings)
logger = structlog.get_logger(__name__)

STALE_PROCESSING_AGE = timedelta(minutes=10)
RECONCILE_BATCH = 50


async def recover_stale_processing(session: AsyncSession, now: datetime) -> int:
    rows = list(
        await session.scalars(
            select(CRMDelivery)
            .where(
                CRMDelivery.status == CRMDeliveryStatus.PROCESSING.value,
                CRMDelivery.processing_at.is_not(None),
                CRMDelivery.processing_at <= now - STALE_PROCESSING_AGE,
            )
            .with_for_update(skip_locked=True)
            .limit(RECONCILE_BATCH)
        )
    )
    for delivery in rows:
        if delivery.acknowledged_at is not None:
            delivery.status = CRMDeliveryStatus.ACKNOWLEDGED.value
            delivery.verification_status = "pending"
            delivery.next_verification_at = now
        else:
            connection = await session.scalar(
                select(CRMConnection).where(
                    CRMConnection.id == delivery.connection_id, CRMConnection.tenant_id == delivery.tenant_id
                )
            )
            await _mark_failure(
                session,
                delivery,
                connection,
                CRMError(
                    NormalizedCRMErrorCode.TIMEOUT,
                    "Delivery worker stopped before processing completed",
                    retryable=True,
                ),
            )
            attempt = await session.scalar(
                select(CRMDeliveryAttempt).where(
                    CRMDeliveryAttempt.tenant_id == delivery.tenant_id,
                    CRMDeliveryAttempt.delivery_id == delivery.id,
                    CRMDeliveryAttempt.attempt_number == delivery.attempt_count,
                )
            )
            if attempt is not None and attempt.finished_at is None:
                attempt.finished_at = now
                attempt.result_status = "worker_interrupted"
                attempt.normalized_error_code = "worker_interrupted"
        session.add(
            LeadActivityEvent(
                tenant_id=delivery.tenant_id,
                lead_id=delivery.lead_id,
                event_type="lead.crm.delivery.recovered.v1",
                correlation_id=delivery.correlation_id,
                details_json={"deliveryId": str(delivery.id), "status": delivery.status},
            )
        )
    return len(rows)


async def reconcile_verified_records(session: AsyncSession) -> tuple[int, int]:
    now = datetime.now(UTC)
    rows = list(
        await session.scalars(
            select(CRMDelivery)
            .where(
                CRMDelivery.status.in_(
                    (CRMDeliveryStatus.ACKNOWLEDGED.value, CRMDeliveryStatus.VERIFYING.value)
                ),
                CRMDelivery.acknowledged_at.is_not(None),
                CRMDelivery.verification_status.in_(("pending", "retrying")),
                or_(CRMDelivery.next_verification_at.is_(None), CRMDelivery.next_verification_at <= now),
            )
            .order_by(CRMDelivery.acknowledged_at)
            .with_for_update(skip_locked=True)
            .limit(RECONCILE_BATCH)
        )
    )
    verified = 0
    deferred = 0
    for delivery in rows:
        if await verify_delivery(session, delivery):
            verified += 1
        elif delivery.verification_status == "retrying":
            deferred += 1
    return verified, deferred


async def run_once(session: AsyncSession) -> dict[str, int]:
    now = datetime.now(UTC)
    recovered = await recover_stale_processing(session, now)
    verified, deferred = await reconcile_verified_records(session)
    await session.commit()
    return {"recovered": recovered, "verified": verified, "deferred": deferred}


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
    logger.info("crm_reconciliation_worker_started")
    try:
        while not stop.is_set():
            try:
                async with factory() as session:
                    result = await run_once(session)
                if any(result.values()):
                    logger.info("crm_reconciliation_completed", **result)
            except Exception as exc:
                logger.exception("crm_reconciliation_failed", error=type(exc).__name__)
            try:
                await asyncio.wait_for(stop.wait(), timeout=30.0)
            except TimeoutError:
                pass
    finally:
        await engine.dispose()
        logger.info("crm_reconciliation_worker_stopped")


def main() -> None:
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
