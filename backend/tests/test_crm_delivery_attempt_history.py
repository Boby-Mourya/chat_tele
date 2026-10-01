from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from northstar_api.database import Base
from northstar_api.lead_crm.models import CRMConnection, CRMDelivery, CRMDeliveryAttempt
from northstar_api.models import Agent, Lead, Role, Tenant, Workspace, WorkspaceRole
from northstar_api.routers.crm_delivery_attempts import list_crm_delivery_attempts
from northstar_api.security import Principal


async def test_delivery_attempt_history_is_ordered_safe_and_workspace_scoped() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        tenant = Tenant(slug=f"attempt-history-{uuid4().hex}", name="Attempt History")
        session.add(tenant)
        await session.flush()

        first_workspace = Workspace(
            tenant_id=tenant.id,
            name="Primary CRM Workspace",
            slug=f"primary-{uuid4().hex[:10]}",
        )
        second_workspace = Workspace(
            tenant_id=tenant.id,
            name="Other CRM Workspace",
            slug=f"other-{uuid4().hex[:10]}",
        )
        session.add_all([first_workspace, second_workspace])
        await session.flush()

        first_agent = Agent(
            tenant_id=tenant.id,
            workspace_id=first_workspace.id,
            name="Primary Lead Agent",
        )
        second_agent = Agent(
            tenant_id=tenant.id,
            workspace_id=second_workspace.id,
            name="Other Lead Agent",
        )
        session.add_all([first_agent, second_agent])
        await session.flush()

        first_lead = Lead(
            tenant_id=tenant.id,
            workspace_id=first_workspace.id,
            agent_id=first_agent.id,
            name="Primary Lead",
            status="new",
            consent=False,
            fields_json={},
        )
        second_lead = Lead(
            tenant_id=tenant.id,
            workspace_id=second_workspace.id,
            agent_id=second_agent.id,
            name="Other Lead",
            status="new",
            consent=False,
            fields_json={},
        )
        session.add_all([first_lead, second_lead])
        await session.flush()

        crm_connection = CRMConnection(
            tenant_id=tenant.id,
            public_id=f"crm_{uuid4().hex}",
            provider="generic_rest",
            name="Attempt History CRM",
            status="healthy",
            configuration_json={},
        )
        session.add(crm_connection)
        await session.flush()

        first_delivery = CRMDelivery(
            tenant_id=tenant.id,
            lead_id=first_lead.id,
            connection_id=crm_connection.id,
            provider="generic_rest",
            operation="upsert",
            idempotency_key=f"attempt-primary-{uuid4().hex}",
            status="failed",
            attempt_count=2,
        )
        second_delivery = CRMDelivery(
            tenant_id=tenant.id,
            lead_id=second_lead.id,
            connection_id=crm_connection.id,
            provider="generic_rest",
            operation="upsert",
            idempotency_key=f"attempt-other-{uuid4().hex}",
            status="failed",
            attempt_count=1,
        )
        session.add_all([first_delivery, second_delivery])
        await session.flush()

        now = datetime.now(UTC)
        session.add_all(
            [
                CRMDeliveryAttempt(
                    tenant_id=tenant.id,
                    delivery_id=first_delivery.id,
                    attempt_number=2,
                    started_at=now + timedelta(seconds=2),
                    finished_at=now + timedelta(seconds=3),
                    http_status=429,
                    latency_ms=180,
                    result_status="retryable_error",
                    normalized_error_code="rate_limited",
                    provider_error_code="TOO_MANY_REQUESTS",
                    provider_request_id="provider-request-2",
                    metadata_json={"secret": "must-not-be-returned"},
                ),
                CRMDeliveryAttempt(
                    tenant_id=tenant.id,
                    delivery_id=first_delivery.id,
                    attempt_number=1,
                    started_at=now,
                    finished_at=now + timedelta(seconds=1),
                    http_status=500,
                    latency_ms=120,
                    result_status="retryable_error",
                    normalized_error_code="provider_unavailable",
                    provider_error_code="SERVER_ERROR",
                    provider_request_id="provider-request-1",
                    metadata_json={"payload": {"email": "private@example.com"}},
                ),
                CRMDeliveryAttempt(
                    tenant_id=tenant.id,
                    delivery_id=second_delivery.id,
                    attempt_number=1,
                    started_at=now,
                    result_status="failed",
                    metadata_json={"private": True},
                ),
            ]
        )
        await session.commit()

        principal = Principal(
            user_id=uuid4(),
            tenant_id=tenant.id,
            role=Role.OWNER,
            token_id="attempt-history-test",
            workspace_id=first_workspace.id,
            workspace_role=WorkspaceRole.ADMIN,
            permissions=frozenset({"*"}),
        )

        attempts = await list_crm_delivery_attempts(first_delivery.id, principal, session)
        assert [attempt.attempt_number for attempt in attempts] == [1, 2]
        assert attempts[0].http_status == 500
        assert attempts[0].latency_ms == 120
        assert attempts[0].normalized_error_code == "provider_unavailable"
        assert attempts[0].provider_error_code == "SERVER_ERROR"
        assert attempts[0].provider_request_id == "provider-request-1"
        assert attempts[1].http_status == 429
        assert "metadata" not in attempts[0].model_dump()
        assert "payload" not in attempts[0].model_dump()

        with pytest.raises(HTTPException) as failure:
            await list_crm_delivery_attempts(second_delivery.id, principal, session)
        assert failure.value.status_code == 404
        assert failure.value.detail == "CRM delivery not found"

    await engine.dispose()
