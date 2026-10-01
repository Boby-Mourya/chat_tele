from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from northstar_api.database import Base
from northstar_api.lead_crm.models import CRMConnection, CRMDelivery, IntegrationDeadLetter
from northstar_api.lead_crm.workspace_scope import WorkspaceCRMConnection
from northstar_api.models import Agent, Lead, Role, Tenant, Workspace, WorkspaceRole
from northstar_api.routers.crm_operations import crm_operational_health
from northstar_api.security import Principal


@pytest.fixture
async def operations_case() -> AsyncIterator[tuple[AsyncSession, Principal]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        tenant = Tenant(slug=f"ops-{uuid4().hex}", name="CRM operations")
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

        primary_connection = CRMConnection(
            tenant_id=tenant.id,
            provider="zoho",
            name="Primary Zoho",
            status="healthy",
            configuration_json={},
        )
        other_connection = CRMConnection(
            tenant_id=tenant.id,
            provider="salesforce",
            name="Other Salesforce",
            status="unhealthy",
            last_error="Other workspace failure must not leak",
            configuration_json={},
        )
        session.add_all([primary_connection, other_connection])
        await session.flush()
        session.add_all([
            WorkspaceCRMConnection(
                tenant_id=tenant.id,
                workspace_id=workspace.id,
                connection_id=primary_connection.id,
            ),
            WorkspaceCRMConnection(
                tenant_id=tenant.id,
                workspace_id=other_workspace.id,
                connection_id=other_connection.id,
            ),
        ])
        await session.flush()

        deliveries = [
            CRMDelivery(
                tenant_id=tenant.id,
                lead_id=lead.id,
                connection_id=primary_connection.id,
                provider="zoho",
                operation="upsert",
                idempotency_key=f"queued-{uuid4().hex}",
                status="queued",
            ),
            CRMDelivery(
                tenant_id=tenant.id,
                lead_id=lead.id,
                connection_id=primary_connection.id,
                provider="zoho",
                operation="upsert",
                idempotency_key=f"retrying-{uuid4().hex}",
                status="retrying",
            ),
            CRMDelivery(
                tenant_id=tenant.id,
                lead_id=lead.id,
                connection_id=primary_connection.id,
                provider="zoho",
                operation="upsert",
                idempotency_key=f"dead-{uuid4().hex}",
                status="dead_letter",
            ),
            CRMDelivery(
                tenant_id=tenant.id,
                lead_id=other_lead.id,
                connection_id=other_connection.id,
                provider="salesforce",
                operation="upsert",
                idempotency_key=f"other-dead-{uuid4().hex}",
                status="dead_letter",
            ),
            # Deliberately malformed legacy-style row: the CRM belongs to the
            # active Workspace, but the Lead belongs to another Workspace. The
            # operations endpoint must still exclude this row through Lead scope.
            CRMDelivery(
                tenant_id=tenant.id,
                lead_id=other_lead.id,
                connection_id=primary_connection.id,
                provider="zoho",
                operation="upsert",
                idempotency_key=f"cross-workspace-{uuid4().hex}",
                status="dead_letter",
            ),
        ]
        session.add_all(deliveries)
        await session.flush()
        session.add_all([
            IntegrationDeadLetter(
                tenant_id=tenant.id,
                delivery_id=deliveries[2].id,
                status="open",
                reason_code="network_error",
                reason_message="Primary provider timed out",
            ),
            IntegrationDeadLetter(
                tenant_id=tenant.id,
                delivery_id=deliveries[3].id,
                status="open",
                reason_code="network_error",
                reason_message="Other workspace must not leak",
            ),
            IntegrationDeadLetter(
                tenant_id=tenant.id,
                delivery_id=deliveries[4].id,
                status="open",
                reason_code="network_error",
                reason_message="Cross-workspace Lead must not leak through primary CRM",
            ),
        ])
        await session.commit()

        principal = Principal(
            user_id=uuid4(),
            tenant_id=tenant.id,
            role=Role.MEMBER,
            token_id="crm-ops",
            workspace_id=workspace.id,
            workspace_role=WorkspaceRole.MANAGER,
            permissions=frozenset({"crm.view"}),
        )
        yield session, principal

    await engine.dispose()


async def test_operational_health_aggregates_only_active_workspace(operations_case) -> None:
    session, principal = operations_case

    result = await crm_operational_health(principal, session)

    assert result.overall_status == "attention"
    assert result.connection_count == 1
    assert result.healthy_connections == 0
    assert result.attention_connections == 1
    assert result.pending_deliveries == 1
    assert result.retrying_deliveries == 1
    assert result.failed_deliveries == 1
    assert result.open_dead_letters == 1
    assert len(result.connections) == 1
    connection = result.connections[0]
    assert connection.name == "Primary Zoho"
    assert connection.provider == "zoho"
    assert connection.pending_deliveries == 1
    assert connection.retrying_deliveries == 1
    assert connection.failed_deliveries == 1
    assert connection.open_dead_letters == 1
    assert "Other workspace" not in (connection.last_error or "")


async def test_operational_health_empty_workspace_is_explicit(operations_case) -> None:
    session, principal = operations_case
    empty_workspace = Workspace(
        tenant_id=principal.tenant_id,
        name="Empty workspace",
        slug=f"empty-{uuid4().hex[:8]}",
    )
    session.add(empty_workspace)
    await session.commit()

    empty_principal = Principal(
        user_id=principal.user_id,
        tenant_id=principal.tenant_id,
        role=principal.role,
        token_id="crm-ops-empty",
        workspace_id=empty_workspace.id,
        workspace_role=WorkspaceRole.MANAGER,
        permissions=frozenset({"crm.view"}),
    )
    result = await crm_operational_health(empty_principal, session)

    assert result.overall_status == "empty"
    assert result.connection_count == 0
    assert result.connections == []
