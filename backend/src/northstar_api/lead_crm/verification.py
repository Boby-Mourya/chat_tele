from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.lead_crm.connection_context import load_connection_context
from northstar_api.lead_crm.connectors import CRMConnectionContext, CRMError, crm_registry
from northstar_api.lead_crm.domain import CRMProvider, NormalizedCRMErrorCode
from northstar_api.lead_crm.models import CRMConnection, CRMDelivery, IntegrationDeadLetter, LeadActivityEvent
from northstar_api.services.outbox import enqueue_event


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        return min(max(int(value), minimum), maximum)
    except (TypeError, ValueError, OverflowError):
        return default


def _extract(value: Any, path: str) -> Any:
    current = value
    for part in path.removeprefix("$.").split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def verify_record(
    context: CRMConnectionContext, record: dict[str, Any], external_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """Require positive evidence, not merely a successful GET or empty object.

    Identity verification is mandatory. Optional verificationFields maps exact
    transmitted payload paths to read-back paths. Evidence identifies the scope
    without retaining the provider's complete response or customer field values.
    """
    default_id = {CRMProvider.SALESFORCE: "Id", CRMProvider.DYNAMICS365: "leadid"}.get(context.provider, "id")
    id_path = str(context.configuration.get("readBackIdPath") or default_id)
    actual_id = _extract(record, id_path)
    if (
        not external_id.strip()
        or not isinstance(actual_id, (str, int))
        or isinstance(actual_id, bool)
        or str(actual_id) != external_id
    ):
        raise CRMError(
            NormalizedCRMErrorCode.VALIDATION_ERROR,
            "CRM read-back did not prove the acknowledged record ID",
        )
    fields = context.configuration.get("verificationFields", {})
    if not isinstance(fields, dict) or len(fields) > 100:
        raise CRMError(
            NormalizedCRMErrorCode.CONFIGURATION_ERROR,
            "verificationFields must map at most 100 payload paths to read-back paths",
        )
    compared: list[str] = []
    for source, target in fields.items():
        if not isinstance(target, str) or not target:
            raise CRMError(
                NormalizedCRMErrorCode.CONFIGURATION_ERROR, "Read-back paths must be non-empty strings"
            )
        expected = _extract(payload, str(source))
        actual = _extract(record, target)
        if expected is None or actual is None or actual != expected:
            raise CRMError(
                NormalizedCRMErrorCode.VALIDATION_ERROR,
                "CRM read-back values do not match the transmitted payload",
                retryable=True,
            )
        compared.append(str(source))
    return {
        "recordIdMatched": True,
        "fieldsCompared": compared,
        "scope": "mapped_fields" if compared else "record_identity",
    }


def _event(session: AsyncSession, delivery: CRMDelivery, event_type: str, **details: Any) -> None:
    summary = {
        "deliveryId": str(delivery.id),
        "provider": delivery.provider,
        "externalRecordId": delivery.external_record_id,
        "verificationStatus": delivery.verification_status,
        "verificationAttempt": delivery.verification_attempt_count,
        **details,
    }
    session.add(
        LeadActivityEvent(
            tenant_id=delivery.tenant_id,
            lead_id=delivery.lead_id,
            event_type=event_type,
            correlation_id=delivery.correlation_id,
            details_json=summary,
        )
    )
    enqueue_event(
        session,
        tenant_id=delivery.tenant_id,
        aggregate_type="crm_delivery",
        aggregate_id=delivery.id,
        event_type=event_type,
        payload={"leadId": str(delivery.lead_id), **summary},
    )


async def verification_failed(
    session: AsyncSession, delivery: CRMDelivery, connection: CRMConnection | None, error: CRMError
) -> None:
    """Preserve the irreversible provider ACK; never requeue a remote write."""
    now = datetime.now(UTC)
    delivery.status = "acknowledged"
    delivery.next_retry_at = None
    delivery.verified_at = None
    delivery.verification_error_code = error.code.value
    delivery.verification_error_message = (
        "CRM read-back verification failed; provider acknowledgement is preserved"
    )
    delivery.verification_evidence_json = {}
    config = connection.configuration_json if connection else {}
    limit = bounded_int(config.get("verificationMaxAttempts", 5), 5, 1, 20)
    if connection:
        connection.last_failure_at = now
        connection.last_error = error.code.value
    if error.requires_reconnect:
        delivery.verification_status = "auth_required"
        delivery.next_verification_at = None
        if connection:
            connection.status = "auth_required"
    elif (error.retryable or error.http_status == 404) and delivery.verification_cycle_attempts < limit:
        delivery.verification_status = "retrying"
        delay = bounded_int(
            error.retry_after_seconds, min(900, 2 ** min(delivery.verification_cycle_attempts, 9)), 1, 3600
        )
        delivery.next_verification_at = now + timedelta(seconds=delay)
    else:
        delivery.verification_status = "failed"
        delivery.next_verification_at = None
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
                    reason_message="Read-back verification failed; do not resend the acknowledged write",
                    metadata_json={"phase": "verification", "attempts": delivery.verification_attempt_count},
                )
            )
    _event(session, delivery, "lead.crm.verification.failed.v1", errorCode=error.code.value)


async def verify_delivery(session: AsyncSession, delivery: CRMDelivery) -> bool:
    """The caller locks the delivery and commits the evidence atomically.

    A crash after GET safely replays a GET, never the already-acknowledged write.
    """
    if delivery.acknowledged_at is None or delivery.status not in {"acknowledged", "verifying"}:
        return False
    if delivery.verification_status not in {"pending", "retrying"}:
        return False
    if delivery.next_verification_at and as_utc(delivery.next_verification_at) > datetime.now(UTC):
        return False
    connector = crm_registry.get(CRMProvider(delivery.provider))
    if not connector.capabilities.read_back:
        delivery.status = "acknowledged"
        delivery.verification_status = "unsupported"
        delivery.next_verification_at = None
        delivery.verified_at = None
        delivery.verification_evidence_json = {"scope": "not_supported"}
        _event(session, delivery, "lead.crm.verification.unsupported.v1")
        return False
    delivery.verification_attempt_count += 1
    delivery.verification_cycle_attempts += 1
    connection: CRMConnection | None = None
    started = time.monotonic()
    try:
        if not delivery.external_record_id:
            raise CRMError(
                NormalizedCRMErrorCode.VALIDATION_ERROR, "Provider acknowledgement has no record ID"
            )
        connection, context = await load_connection_context(
            session, tenant_id=delivery.tenant_id, connection_id=delivery.connection_id
        )
        delivery.status = "verifying"
        record = await connector.get_lead(context, delivery.external_record_id)
        evidence = verify_record(context, record, delivery.external_record_id, delivery.payload_json or {})
        delivery.status = "verified"
        delivery.verification_status = "verified"
        delivery.verified_at = datetime.now(UTC)
        delivery.next_verification_at = None
        delivery.verification_error_code = None
        delivery.verification_error_message = None
        delivery.verification_evidence_json = evidence
        _event(
            session,
            delivery,
            "lead.crm.delivery.verified.v1",
            evidence=evidence,
            latencyMs=int((time.monotonic() - started) * 1000),
        )
        return True
    except CRMError as exc:
        await verification_failed(session, delivery, connection, exc)
    except (ValueError, TypeError, KeyError):
        await verification_failed(
            session,
            delivery,
            connection,
            CRMError(NormalizedCRMErrorCode.VALIDATION_ERROR, "Malformed CRM read-back response"),
        )
    return False
