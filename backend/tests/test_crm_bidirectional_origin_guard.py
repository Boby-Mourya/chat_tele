from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from northstar_api.database import Base
from northstar_api.lead_crm.models import CRMConnection, CRMDelivery, CRMRoute, LeadActivityEvent, LeadProfile
from northstar_api.lead_crm.workspace_routing import workspace_crm_route_service
from northstar_api.lead_crm.workspace_scope import WorkspaceCRMConnection, WorkspaceCRMRoute
from northstar_api.models import Agent, Lead, Tenant, Workspace
from northstar_api.workers.crm_router_consumer import _origin_connection_id
from northstar_api.workers.crm_webhook_consumer import _fanout_payload


@pytest.fixture
async def routing_case() -> AsyncIterator[
    tuple[AsyncSession, Tenant, Workspace, Lead, CRMConnection, CRMConnection]
]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        tenant = Tenant(slug=f"crm-origin-{uuid4().hex}", name="CRM origin tenant")
        session.add(tenant)
        await session.flush()
        workspace = Workspace(
            tenant_id=tenant.id,
            name="CRM origin workspace",
            slug=f"origin-{uuid4().hex[:8]}",
        )
        session.add(workspace)
        await session.flush()
        agent = Agent(tenant_id=tenant.id, workspace_id=workspace.id, name="Origin agent")
        session.add(agent)
        await session.flush()
        lead = Lead(
            tenant_id=tenant.id,
            workspace_id=workspace.id,
            agent_id=agent.id,
            name="Bidirectional lead",
            email="lead@example.com",
            status="new",
            consent=True,
            fields_json={},
        )
        session.add(lead)
        await session.flush()
        session.add(
            LeadProfile(
                tenant_id=tenant.id,
                lead_id=lead.id,
                lifecycle_status="new",
                qualification_status="pending",
                qualification_score=0,
                consent_status="granted",
                custom_fields_json={},
            )
        )
        origin = CRMConnection(
            tenant_id=tenant.id,
            provider="salesforce",
            name="Origin CRM",
            status="healthy",
            configuration_json={},
        )
        destination = CRMConnection(
            tenant_id=tenant.id,
            provider="hubspot",
            name="Destination CRM",
            status="healthy",
            configuration_json={},
        )
        session.add_all([origin, destination])
        await session.flush()
        session.add_all([
            WorkspaceCRMConnection(
                tenant_id=tenant.id,
                workspace_id=workspace.id,
                connection_id=origin.id,
                auto_sync_new_leads=True,
                auto_sync_updates=True,
            ),
            WorkspaceCRMConnection(
                tenant_id=tenant.id,
                workspace_id=workspace.id,
                connection_id=destination.id,
                auto_sync_new_leads=True,
                auto_sync_updates=True,
            ),
        ])
        route = CRMRoute(
            tenant_id=tenant.id,
            name="All CRM destinations",
            enabled=True,
            priority=10,
            conditions_json={},
            actions_json={"connectionIds": [str(origin.id), str(destination.id)]},
        )
        session.add(route)
        await session.flush()
        session.add(
            WorkspaceCRMRoute(
                tenant_id=tenant.id,
                workspace_id=workspace.id,
                route_id=route.id,
            )
        )
        await session.commit()
        yield session, tenant, workspace, lead, origin, destination

    await engine.dispose()


def test_inbound_fanout_payload_is_only_created_for_real_changes() -> None:
    lead_id = uuid4()
    connection_id = uuid4()

    assert _fanout_payload(lead_id, connection_id, {}) is None
    assert _fanout_payload(lead_id, connection_id, {"name": "Updated"}) == {
        "leadId": str(lead_id),
        "reason": "crm_inbound",
        "originConnectionId": str(connection_id),
    }


def test_router_origin_connection_parser_is_strict() -> None:
    connection_id = uuid4()

    assert _origin_connection_id({}) is None
    assert _origin_connection_id({"originConnectionId": ""}) is None
    assert _origin_connection_id({"originConnectionId": str(connection_id)}) == connection_id
    with pytest.raises(ValueError, match="invalid originConnectionId"):
        _origin_connection_id({"originConnectionId": "not-a-uuid"})


async def test_inbound_sync_skips_origin_and_routes_to_other_workspace_crm(routing_case) -> None:
    session, tenant, workspace, lead, origin, destination = routing_case

    deliveries = await workspace_crm_route_service.create_deliveries(
        session,
        tenant_id=tenant.id,
        lead_id=lead.id,
        correlation_id="crm-inbound-event",
        sync_reason="crm_inbound",
        origin_connection_id=origin.id,
    )
    await session.commit()

    assert [delivery.connection_id for delivery in deliveries] == [destination.id]
    persisted = list(
        await session.scalars(
            select(CRMDelivery)
            .where(CRMDelivery.tenant_id == tenant.id, CRMDelivery.lead_id == lead.id)
            .order_by(CRMDelivery.created_at, CRMDelivery.id)
        )
    )
    assert [delivery.connection_id for delivery in persisted] == [destination.id]
    suppressed = list(
        await session.scalars(
            select(LeadActivityEvent).where(
                LeadActivityEvent.tenant_id == tenant.id,
                LeadActivityEvent.lead_id == lead.id,
                LeadActivityEvent.event_type == "lead.crm.delivery.suppressed.v1",
            )
        )
    )
    assert len(suppressed) == 1
    assert suppressed[0].details_json == {
        "workspaceId": str(workspace.id),
        "connectionId": str(origin.id),
        "reason": "inbound_origin",
    }


async def test_normal_sync_without_origin_preserves_existing_routing(routing_case) -> None:
    session, tenant, _, lead, origin, destination = routing_case

    deliveries = await workspace_crm_route_service.create_deliveries(
        session,
        tenant_id=tenant.id,
        lead_id=lead.id,
        correlation_id="platform-update",
        sync_reason="manual",
    )
    await session.commit()

    assert {delivery.connection_id for delivery in deliveries} == {origin.id, destination.id}
    persisted = list(
        await session.scalars(
            select(CRMDelivery).where(
                CRMDelivery.tenant_id == tenant.id,
                CRMDelivery.lead_id == lead.id,
            )
        )
    )
    assert {delivery.connection_id for delivery in persisted} == {origin.id, destination.id}
