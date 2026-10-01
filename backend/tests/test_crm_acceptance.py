from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from northstar_api.database import Base
from northstar_api.lead_crm.circuit import allow_request, record_failure, record_success
from northstar_api.lead_crm.connectors import (
    CRMCapabilities,
    CRMConnectionContext,
    CRMConnector,
    CRMDeliveryResult,
    CRMError,
    CRMHealthResult,
    crm_registry,
)
from northstar_api.lead_crm.domain import (
    CRMDeliveryStatus,
    CRMOperation,
    CRMProvider,
    IntegrationHealthStatus,
    NormalizedCRMErrorCode,
    validate_delivery_transition,
)
from northstar_api.lead_crm.mapping import build_mapped_payload
from northstar_api.lead_crm.models import (
    ContactIdentity,
    CRMConnection,
    CRMDelivery,
    CRMDeliveryAttempt,
    CRMExternalReference,
    CRMFieldMapping,
    CRMRoute,
    IntegrationDeadLetter,
)
from northstar_api.lead_crm.services import crm_route_service, lead_domain_service
from northstar_api.lead_crm.verification import as_utc, verify_record
from northstar_api.models import Agent, Lead, OutboxEvent, Role, Tenant, Workspace
from northstar_api.routers.crm import cancel_crm_delivery, retry_crm_delivery
from northstar_api.security import Principal
from northstar_api.workers import crm_router_consumer
from northstar_api.workers.crm_delivery_worker import process_delivery
from northstar_api.workers.crm_reconciliation import run_once


class RecordingConnector(CRMConnector):
    provider = CRMProvider.GENERIC_REST

    def __init__(self, *, read_back: bool = True) -> None:
        self.capabilities = CRMCapabilities(create=True, update=True, upsert=True, read_back=read_back)
        self.writes = 0
        self.reads = 0
        self.write_error: CRMError | None = None
        self.read_error: CRMError | None = None
        self.record: dict[str, Any] = {"id": "crm-record-1"}
        self.sent: list[dict[str, Any]] = []

    async def health_check(self, context: CRMConnectionContext) -> CRMHealthResult:
        return CRMHealthResult(IntegrationHealthStatus.HEALTHY, {"api": "up"})

    async def create_lead(
        self, context: CRMConnectionContext, payload: dict[str, Any], *, idempotency_key: str
    ) -> CRMDeliveryResult:
        self.writes += 1
        self.sent.append(json.loads(json.dumps(payload)))
        if self.write_error:
            raise self.write_error
        return CRMDeliveryResult(True, CRMOperation.CREATE, "crm-record-1", 201)

    async def update_lead(
        self,
        context: CRMConnectionContext,
        external_id: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> CRMDeliveryResult:
        result = await self.create_lead(context, payload, idempotency_key=idempotency_key)
        return CRMDeliveryResult(result.accepted, CRMOperation.UPDATE, external_id, 200)

    async def upsert_lead(
        self, context: CRMConnectionContext, payload: dict[str, Any], *, idempotency_key: str
    ) -> CRMDeliveryResult:
        result = await self.create_lead(context, payload, idempotency_key=idempotency_key)
        return CRMDeliveryResult(
            result.accepted, CRMOperation.UPSERT, result.external_record_id, result.http_status
        )

    async def get_lead(self, context: CRMConnectionContext, external_id: str) -> dict[str, Any]:
        self.reads += 1
        if self.read_error:
            raise self.read_error
        return dict(self.record)


@pytest.fixture
async def case() -> AsyncIterator[tuple[AsyncSession, Lead, CRMConnection, CRMDelivery]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        tenant = Tenant(slug=f"acceptance-{uuid4().hex}", name="CRM acceptance")
        session.add(tenant)
        await session.flush()
        workspace = Workspace(tenant_id=tenant.id, name="Acceptance workspace", slug="acceptance")
        session.add(workspace)
        await session.flush()
        agent = Agent(tenant_id=tenant.id, workspace_id=workspace.id, name="CRM acceptance agent")
        session.add(agent)
        await session.flush()
        lead = Lead(
            tenant_id=tenant.id,
            workspace_id=workspace.id,
            agent_id=agent.id,
            name="Test Lead",
            email="lead@example.com",
            phone="+15550101001",
            status="new",
            consent=True,
            fields_json={},
        )
        session.add(lead)
        await session.flush()
        await lead_domain_service.qualify(
            session,
            lead=lead,
            score=85,
            reason="Acceptance fixture",
            actor_id=None,
            correlation_id="acceptance",
        )
        connection = CRMConnection(
            tenant_id=tenant.id,
            public_id=f"crm_{uuid4().hex}",
            provider="generic_rest",
            name="CRM acceptance destination",
            status="healthy",
            configuration_json={},
        )
        session.add(connection)
        await session.flush()
        session.add(
            CRMRoute(
                tenant_id=tenant.id,
                name="Qualified leads",
                enabled=True,
                priority=10,
                conditions_json={"qualificationStatus": "qualified"},
                actions_json={"connectionIds": [str(connection.id)]},
            )
        )
        await session.flush()
        deliveries = await crm_route_service.create_deliveries(session, tenant_id=tenant.id, lead_id=lead.id)
        assert len(deliveries) == 1
        await session.commit()
        yield session, lead, connection, deliveries[0]
    await engine.dispose()


def context(provider: CRMProvider = CRMProvider.GENERIC_REST, **configuration: Any) -> CRMConnectionContext:
    return CRMConnectionContext(uuid4(), uuid4(), provider, configuration, {})


@pytest.mark.parametrize("record", [{}, {"message": "ok"}, {"id": None}, {"id": "another-record"}])
def test_readback_requires_positive_record_identity(record: dict[str, Any]) -> None:
    with pytest.raises(CRMError):
        verify_record(context(), record, "crm-record-1", {})


@pytest.mark.parametrize(
    "provider,key",
    [
        (CRMProvider.ZOHO, "id"),
        (CRMProvider.GENERIC_REST, "id"),
        (CRMProvider.SALESFORCE, "Id"),
        (CRMProvider.DYNAMICS365, "leadid"),
    ],
)
def test_readback_identity_evidence_is_provider_aware(provider: CRMProvider, key: str) -> None:
    evidence = verify_record(context(provider), {key: "crm-record-1"}, "crm-record-1", {})
    assert evidence == {"recordIdMatched": True, "fieldsCompared": [], "scope": "record_identity"}


def test_readback_distinguishes_field_value_proof_from_identity_only() -> None:
    ctx = context(verificationFields={"email": "properties.email"})
    evidence = verify_record(
        ctx,
        {"id": "crm-record-1", "properties": {"email": "lead@example.com"}},
        "crm-record-1",
        {"email": "lead@example.com"},
    )
    assert evidence["scope"] == "mapped_fields"
    assert evidence["fieldsCompared"] == ["email"]
    with pytest.raises(CRMError) as failure:
        verify_record(
            ctx,
            {"id": "crm-record-1", "properties": {"email": "outdated@example.com"}},
            "crm-record-1",
            {"email": "lead@example.com"},
        )
    assert failure.value.retryable


@pytest.mark.parametrize(
    "current,target",
    [
        (CRMDeliveryStatus.ACKNOWLEDGED, CRMDeliveryStatus.RETRYING),
        (CRMDeliveryStatus.VERIFYING, CRMDeliveryStatus.RETRYING),
        (CRMDeliveryStatus.ACKNOWLEDGED, CRMDeliveryStatus.VERIFIED),
    ],
)
def test_state_machine_cannot_resend_or_skip_proof_after_ack(
    current: CRMDeliveryStatus, target: CRMDeliveryStatus
) -> None:
    with pytest.raises(ValueError):
        validate_delivery_transition(current, target)


async def test_full_persisted_pipeline_has_outbox_ack_reference_and_verification(
    case, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, lead, connection, delivery = case
    connector = RecordingConnector()
    monkeypatch.setattr(crm_registry, "get", lambda _: connector)
    await process_delivery(session, delivery.id)
    await session.refresh(delivery)
    assert delivery.status == "verified"
    assert delivery.acknowledged_at is not None and delivery.verified_at is not None
    assert delivery.verification_status == "verified"
    assert delivery.verification_evidence_json["recordIdMatched"] is True
    assert delivery.payload_json == connector.sent[0]
    assert connector.writes == 1 and connector.reads == 1
    references = list(
        await session.scalars(select(CRMExternalReference).where(CRMExternalReference.lead_id == lead.id))
    )
    assert len(references) == 1 and references[0].external_id == "crm-record-1"
    events = set(
        await session.scalars(select(OutboxEvent.event_type).where(OutboxEvent.tenant_id == lead.tenant_id))
    )
    assert {
        "lead.qualified.v1",
        "lead.crm.sync.requested.v1",
        "lead.crm.delivery.created.v1",
        "lead.crm.delivery.acknowledged.v1",
        "lead.crm.delivery.verified.v1",
    } <= events
    await process_delivery(session, delivery.id)
    assert connector.writes == 1 and connector.reads == 1


async def test_normalized_contact_is_not_falsely_marked_verified(case) -> None:
    session, lead, _, _ = case
    identities = list(
        await session.scalars(select(ContactIdentity).where(ContactIdentity.tenant_id == lead.tenant_id))
    )
    assert identities and all(identity.verified is False for identity in identities)


async def test_same_payload_deduplicates_but_changed_lead_gets_new_delivery(case) -> None:
    session, lead, _, delivery = case
    same = await crm_route_service.create_deliveries(session, tenant_id=lead.tenant_id, lead_id=lead.id)
    assert [item.id for item in same] == [delivery.id]
    lead.email = "updated@example.com"
    await session.flush()
    changed = await crm_route_service.create_deliveries(session, tenant_id=lead.tenant_id, lead_id=lead.id)
    assert len(changed) == 1 and changed[0].id != delivery.id
    assert changed[0].idempotency_key != delivery.idempotency_key


async def test_transient_verification_retries_only_get_never_the_acknowledged_write(
    case, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, _, _, delivery = case
    connector = RecordingConnector()
    connector.read_error = CRMError(NormalizedCRMErrorCode.TIMEOUT, "fixture timeout", retryable=True)
    monkeypatch.setattr(crm_registry, "get", lambda _: connector)
    await process_delivery(session, delivery.id)
    assert delivery.status == "acknowledged" and delivery.verification_status == "retrying"
    original_ack = as_utc(delivery.acknowledged_at)
    assert connector.writes == 1 and connector.reads == 1
    await process_delivery(session, delivery.id)
    assert connector.writes == 1 and connector.reads == 1
    delivery.next_verification_at = datetime.now(UTC) - timedelta(seconds=1)
    connector.read_error = None
    await session.commit()
    result = await run_once(session)
    assert result["verified"] == 1
    assert delivery.status == "verified"
    assert as_utc(delivery.acknowledged_at) == original_ack
    assert connector.writes == 1 and connector.reads == 2
    assert delivery.attempt_count == 1 and delivery.verification_attempt_count == 2


async def test_empty_readback_preserves_ack_and_records_verification_dead_letter(
    case, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, _, _, delivery = case
    connector = RecordingConnector()
    connector.record = {}
    monkeypatch.setattr(crm_registry, "get", lambda _: connector)
    await process_delivery(session, delivery.id)
    assert delivery.status == "acknowledged" and delivery.verified_at is None
    assert delivery.verification_status == "failed" and delivery.next_retry_at is None
    letter = await session.scalar(
        select(IntegrationDeadLetter).where(IntegrationDeadLetter.delivery_id == delivery.id)
    )
    assert letter is not None and letter.metadata_json["phase"] == "verification"
    attempt = await session.scalar(
        select(CRMDeliveryAttempt).where(CRMDeliveryAttempt.delivery_id == delivery.id)
    )
    assert attempt is not None and attempt.result_status == "acknowledged"
    await run_once(session)
    assert connector.writes == 1 and connector.reads == 1


async def test_unsupported_readback_never_becomes_verified_even_in_reconciliation(
    case, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, _, _, delivery = case
    connector = RecordingConnector(read_back=False)
    monkeypatch.setattr(crm_registry, "get", lambda _: connector)
    await process_delivery(session, delivery.id)
    assert delivery.status == "acknowledged" and delivery.verification_status == "unsupported"
    assert delivery.verified_at is None and connector.reads == 0
    await run_once(session)
    assert delivery.status == "acknowledged" and delivery.verified_at is None
    assert connector.writes == 1 and connector.reads == 0


async def test_verification_retry_budget_is_bounded_independently(
    case, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, _, connection, delivery = case
    connection.configuration_json = {"verificationMaxAttempts": 2}
    connector = RecordingConnector()
    connector.read_error = CRMError(
        NormalizedCRMErrorCode.PROVIDER_UNAVAILABLE, "fixture unavailable", retryable=True
    )
    monkeypatch.setattr(crm_registry, "get", lambda _: connector)
    await session.commit()
    await process_delivery(session, delivery.id)
    delivery.next_verification_at = datetime.now(UTC) - timedelta(seconds=1)
    await session.commit()
    await run_once(session)
    assert delivery.status == "acknowledged" and delivery.verification_status == "failed"
    assert delivery.verification_attempt_count == 2
    await run_once(session)
    assert connector.writes == 1 and connector.reads == 2


async def test_write_failure_budget_reaches_dead_letter_with_finished_attempts(
    case, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, _, connection, delivery = case
    connection.configuration_json = {"maxAttempts": 2}
    connector = RecordingConnector()
    connector.write_error = CRMError(
        NormalizedCRMErrorCode.PROVIDER_UNAVAILABLE, "fixture outage", retryable=True
    )
    monkeypatch.setattr(crm_registry, "get", lambda _: connector)
    await session.commit()
    await process_delivery(session, delivery.id)
    assert delivery.status == "retrying" and delivery.acknowledged_at is None
    delivery.next_retry_at = datetime.now(UTC) - timedelta(seconds=1)
    await session.commit()
    await process_delivery(session, delivery.id)
    assert delivery.status == "dead_letter" and delivery.attempt_count == 2
    attempts = list(
        await session.scalars(select(CRMDeliveryAttempt).where(CRMDeliveryAttempt.delivery_id == delivery.id))
    )
    assert len(attempts) == 2
    assert all(attempt.finished_at is not None and attempt.result_status == "failed" for attempt in attempts)
    assert connector.writes == 2 and connector.reads == 0


async def test_degraded_mapping_cannot_send_and_empty_mapping_does_not_fall_back(
    case, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, lead, connection, delivery = case
    connector = RecordingConnector()
    monkeypatch.setattr(crm_registry, "get", lambda _: connector)
    session.add(
        CRMFieldMapping(
            tenant_id=lead.tenant_id,
            connection_id=connection.id,
            object_name="Leads",
            status="degraded",
            mapping_json={"fields": {"email": "Email"}},
        )
    )
    await session.commit()
    await process_delivery(session, delivery.id)
    assert delivery.status == "mapping_error" and connector.writes == 0
    profile = await lead_domain_service.ensure_profile(session, lead=lead)
    assert build_mapped_payload(lead, profile, {"fields": {}}, provider="generic_rest") == {}
    json.dumps(build_mapped_payload(lead, profile, None, provider="generic_rest"))


async def test_manual_verification_retry_and_cancel_preserve_remote_ack(
    case, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, lead, _, delivery = case
    connector = RecordingConnector()
    connector.record = {}
    monkeypatch.setattr(crm_registry, "get", lambda _: connector)
    await process_delivery(session, delivery.id)
    principal = Principal(uuid4(), lead.tenant_id, Role.OWNER, "acceptance")
    with pytest.raises(HTTPException) as cannot_cancel:
        await cancel_crm_delivery(delivery.id, principal, session)
    assert cannot_cancel.value.status_code == 409
    retried = await retry_crm_delivery(delivery.id, principal, session)
    assert retried.status == CRMDeliveryStatus.ACKNOWLEDGED
    connector.record = {"id": "crm-record-1"}
    await run_once(session)
    assert delivery.status == "verified" and connector.writes == 1 and connector.reads == 2


async def test_half_open_circuit_allows_only_one_leased_probe(case) -> None:
    session, lead, connection, _ = case
    assert await allow_request(session, tenant_id=lead.tenant_id, connection_id=connection.id)
    circuit = await record_failure(
        session, tenant_id=lead.tenant_id, connection_id=connection.id, threshold=1, cooldown_seconds=60
    )
    assert not await allow_request(session, tenant_id=lead.tenant_id, connection_id=connection.id)
    circuit.open_until = datetime.now(UTC) - timedelta(seconds=1)
    await session.commit()
    assert await allow_request(session, tenant_id=lead.tenant_id, connection_id=connection.id)
    await session.commit()
    assert not await allow_request(session, tenant_id=lead.tenant_id, connection_id=connection.id)
    await record_success(session, tenant_id=lead.tenant_id, connection_id=connection.id)
    assert await allow_request(session, tenant_id=lead.tenant_id, connection_id=connection.id)


async def test_tenant_cannot_retry_or_cancel_another_tenants_delivery(case) -> None:
    session, _, _, delivery = case
    other = Principal(uuid4(), uuid4(), Role.OWNER, "other-tenant")
    for action in (retry_crm_delivery, cancel_crm_delivery):
        with pytest.raises(HTTPException) as missing:
            await action(delivery.id, other, session)
        assert missing.value.status_code == 404
    assert delivery.status == "queued"


async def test_router_does_not_commit_or_process_later_partition_offsets_after_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []
    stop = SimpleNamespace(stopped=False)

    async def wait() -> None:
        stop.stopped = True

    stop.wait = wait
    stop.set = lambda: setattr(stop, "stopped", True)
    stop.is_set = lambda: stop.stopped

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def scalar(self, statement):
            calls.append(1)
            raise RuntimeError("fixture transaction failed")

    seeks: list[int] = []
    commits: list[object] = []

    class Consumer:
        async def start(self):
            return None

        async def stop(self):
            return None

        async def getmany(self, **kwargs):
            return {
                "partition": [
                    SimpleNamespace(
                        topic="lead.crm.sync.requested.v1", partition=0, offset=offset, value=b"fixture"
                    )
                    for offset in (10, 11)
                ]
            }

        def seek(self, partition, offset):
            seeks.append(offset)

        async def commit(self, offsets):
            commits.append(offsets)

    async def dispose():
        return None

    async def wait_for(awaitable, **kwargs):
        return await awaitable

    event = SimpleNamespace(
        event_id=uuid4(),
        tenant_id=uuid4(),
        event_type="lead.crm.sync.requested.v1",
        payload={"leadId": str(uuid4())},
    )
    monkeypatch.setattr(crm_router_consumer, "build_engine", lambda _: SimpleNamespace(dispose=dispose))
    monkeypatch.setattr(crm_router_consumer, "async_sessionmaker", lambda *args, **kwargs: Session)
    monkeypatch.setattr(crm_router_consumer, "AIOKafkaConsumer", lambda *args, **kwargs: Consumer())
    monkeypatch.setattr(crm_router_consumer, "parse_envelope", lambda _: event)
    monkeypatch.setattr(
        crm_router_consumer,
        "asyncio",
        SimpleNamespace(
            Event=lambda: stop,
            wait_for=wait_for,
            get_running_loop=lambda: SimpleNamespace(add_signal_handler=lambda *args: None),
        ),
    )
    await crm_router_consumer.consume_forever()
    assert calls == [1] and seeks == [10] and commits == []
