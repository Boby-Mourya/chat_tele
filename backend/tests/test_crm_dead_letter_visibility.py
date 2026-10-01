from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from northstar_api.database import Base
from northstar_api.lead_crm.connectors import CRMError
from northstar_api.lead_crm.domain import NormalizedCRMErrorCode
from northstar_api.lead_crm.models import (
    CRMConnection,
    CRMDelivery,
    IntegrationDeadLetter,
    LeadActivityEvent,
)
from northstar_api.models import Agent, Lead, Role, Tenant, Workspace, WorkspaceRole
from northstar_api.routers.crm_dead_letters import list_crm_dead_letters, replay_crm_dead_letter
from northstar_api.security import Principal
from northstar_api.workers.crm_delivery_worker import _mark_failure


@pytest.fixture
async def dead_letter_case() -> AsyncIterator[
    tuple[AsyncSession, Principal, CRMConnection, IntegrationDeadLetter, IntegrationDeadLetter]
]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        tenant = Tenant(slug=f"dlq-{uuid4().hex}", name="Dead-letter tenant")
        session.add(tenant)
        await session.flush()

        workspace = Workspace(
            tenant_id=tenant.id,
            name="Primary workspace",
            slug=f"primary-{uuid4().hex[:8]}",
        )
        other_workspace = Workspace(
            tenant_id=tenant.id,
            name="Other workspace",
            slug=f"other-{uuid4().hex[:8]}",
        )
        session.add_all([workspace, other_workspace])
        await session.flush()

        agent = Agent(tenant_id=tenant.id, workspace_id=workspace.id, name="Primary agent")
        other_agent = Agent(
            tenant_id=tenant.id,
            workspace_id=other_workspace.id,
            name="Other agent",
        )
        session.add_all([agent, other_agent])
        await session.flush()

        lead = Lead(
            tenant_id=tenant.id,
            workspace_id=workspace.id,
            agent_id=agent.id,
            name="Primary lead",
            status="new",
            consent=True,
            fields_json={},
        )
        other_lead = Lead(
            tenant_id=tenant.id,
            workspace_id=other_workspace.id,
            agent_id=other_agent.id,
            name="Other lead",
            status="new",
            consent=True,
            fields_json={},
        )
        session.add_all([lead, other_lead])
        await session.flush()

        connection = CRMConnection(
            tenant_id=tenant.id,
            public_id=f"crm_{uuid4().hex}",
            provider="generic_rest",
            name="Primary CRM",
            status="healthy",
            configuration_json={},
        )
        session.add(connection)
        await session.flush()

        delivery = CRMDelivery(
            tenant_id=tenant.id,
            lead_id=lead.id,
            connection_id=connection.id,
            provider="generic_rest",
            operation="upsert",
            idempotency_key=f"primary-{uuid4().hex}",
            status="dead_letter",
        )
        other_delivery = CRMDelivery(
            tenant_id=tenant.id,
            lead_id=other_lead.id,
            connection_id=connection.id,
            provider="generic_rest",
            operation="upsert",
            idempotency_key=f"other-{uuid4().hex}",
            status="dead_letter",
        )
        session.add_all([delivery, other_delivery])
        await session.flush()

        primary_dead_letter = IntegrationDeadLetter(
            tenant_id=tenant.id,
            delivery_id=delivery.id,
            status="open",
            reason_code="network_error",
            reason_message="Provider timed out",
            metadata_json={"secretDiagnostic": "must-not-be-returned", "httpStatus": 504},
        )
        other_dead_letter = IntegrationDeadLetter(
            tenant_id=tenant.id,
            delivery_id=other_delivery.id,
            status="open",
            reason_code="rate_limit_error",
            reason_message="Provider rate limit exhausted",
            metadata_json={"secretDiagnostic": "other-workspace"},
        )
        session.add_all([primary_dead_letter, other_dead_letter])
        await session.commit()

        principal = Principal(
            user_id=uuid4(),
            tenant_id=tenant.id,
            role=Role.MEMBER,
            token_id="dead-letter-test",
            workspace_id=workspace.id,
            workspace_role=WorkspaceRole.MANAGER,
            permissions=frozenset({"crm.view", "crm.manage"}),
        )
        yield session, principal, connection, primary_dead_letter, other_dead_letter

    await engine.dispose()


async def test_dead_letter_list_is_workspace_scoped_and_safe(dead_letter_case) -> None:
    session, principal, connection, primary_dead_letter, other_dead_letter = dead_letter_case

    rows = await list_crm_dead_letters(
        principal=principal,
        session=session,
        connection_id=None,
        dead_letter_status="open",
    )

    assert [row.id for row in rows] == [primary_dead_letter.id]
    assert other_dead_letter.id not in {row.id for row in rows}
    assert rows[0].connection_id == connection.id
    assert rows[0].reason_code == "network_error"
    assert "metadata_json" not in rows[0].model_dump()
    assert "metadata" not in rows[0].model_dump()


async def test_dead_letter_filters_status_and_connection(dead_letter_case) -> None:
    session, principal, connection, primary_dead_letter, _ = dead_letter_case
    primary_dead_letter.status = "resolved"
    primary_dead_letter.resolved_at = datetime.now(UTC)
    await session.commit()

    open_rows = await list_crm_dead_letters(
        principal=principal,
        session=session,
        connection_id=connection.id,
        dead_letter_status="open",
    )
    resolved_rows = await list_crm_dead_letters(
        principal=principal,
        session=session,
        connection_id=connection.id,
        dead_letter_status="resolved",
    )
    all_rows = await list_crm_dead_letters(
        principal=principal,
        session=session,
        connection_id=connection.id,
        dead_letter_status="all",
    )

    assert open_rows == []
    assert [row.id for row in resolved_rows] == [primary_dead_letter.id]
    assert [row.id for row in all_rows] == [primary_dead_letter.id]


async def test_replay_resolves_incident_and_queues_existing_delivery_retry(dead_letter_case) -> None:
    session, principal, _, primary_dead_letter, _ = dead_letter_case

    result = await replay_crm_dead_letter(primary_dead_letter.id, principal, session)

    assert result.dead_letter_id == primary_dead_letter.id
    assert result.delivery_id == primary_dead_letter.delivery_id
    assert result.dead_letter_status == "resolved"
    assert result.delivery_status == "retrying"

    await session.refresh(primary_dead_letter)
    delivery = await session.get(CRMDelivery, primary_dead_letter.delivery_id)
    assert delivery is not None
    assert delivery.status == "retrying"
    assert delivery.next_retry_at is not None
    assert primary_dead_letter.status == "resolved"
    assert primary_dead_letter.resolved_at is not None
    assert primary_dead_letter.metadata_json["secretDiagnostic"] == "must-not-be-returned"
    assert primary_dead_letter.metadata_json["resolution"]["type"] == "replay_requested"
    assert primary_dead_letter.metadata_json["resolution"]["userId"] == str(principal.user_id)

    activity = list(
        await session.scalars(
            select(LeadActivityEvent).where(
                LeadActivityEvent.tenant_id == principal.tenant_id,
                LeadActivityEvent.event_type == "lead.crm.retry.requested.v1",
            )
        )
    )
    assert len(activity) == 1
    assert activity[0].details_json["deliveryId"] == str(delivery.id)

    with pytest.raises(HTTPException) as repeated:
        await replay_crm_dead_letter(primary_dead_letter.id, principal, session)
    assert repeated.value.status_code == 409


async def test_replay_cannot_cross_workspace_boundary(dead_letter_case) -> None:
    session, principal, _, _, other_dead_letter = dead_letter_case

    with pytest.raises(HTTPException) as denied:
        await replay_crm_dead_letter(other_dead_letter.id, principal, session)

    assert denied.value.status_code == 404
    await session.refresh(other_dead_letter)
    other_delivery = await session.get(CRMDelivery, other_dead_letter.delivery_id)
    assert other_dead_letter.status == "open"
    assert other_delivery is not None and other_delivery.status == "dead_letter"


async def test_failed_replay_cycle_creates_new_open_incident_and_keeps_history(dead_letter_case) -> None:
    session, principal, connection, primary_dead_letter, _ = dead_letter_case
    await replay_crm_dead_letter(primary_dead_letter.id, principal, session)

    delivery = await session.get(CRMDelivery, primary_dead_letter.delivery_id)
    assert delivery is not None
    delivery.retry_cycle_attempts = 5
    await _mark_failure(
        session,
        delivery,
        connection,
        CRMError(
            NormalizedCRMErrorCode.NETWORK_ERROR,
            "Provider unavailable after manual replay",
            retryable=True,
        ),
    )
    await session.commit()

    incidents = list(
        await session.scalars(
            select(IntegrationDeadLetter)
            .where(
                IntegrationDeadLetter.tenant_id == principal.tenant_id,
                IntegrationDeadLetter.delivery_id == delivery.id,
            )
            .order_by(IntegrationDeadLetter.created_at, IntegrationDeadLetter.id)
        )
    )
    assert len(incidents) == 2
    assert {incident.status for incident in incidents} == {"resolved", "open"}
    assert primary_dead_letter.id in {incident.id for incident in incidents if incident.status == "resolved"}
    new_open = next(incident for incident in incidents if incident.status == "open")
    assert new_open.id != primary_dead_letter.id
    assert new_open.reason_code == NormalizedCRMErrorCode.NETWORK_ERROR.value
    assert delivery.status == "dead_letter"
