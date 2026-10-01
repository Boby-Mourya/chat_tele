from __future__ import annotations

from uuid import UUID

from httpx import AsyncClient
from sqlalchemy import select

from northstar_api.database import SessionFactory
from northstar_api.lead_crm.workspace_routing import workspace_crm_route_service
from northstar_api.models import Agent, Lead


async def test_crm_connection_and_routing_are_isolated_by_workspace(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    workspaces_response = await client.get("/api/v1/workspaces", headers=auth_headers)
    assert workspaces_response.status_code == 200, workspaces_response.text
    default_workspace = workspaces_response.json()[0]
    default_workspace_id = default_workspace["id"]
    tenant_id = UUID(default_workspace["tenantId"])
    default_headers = {**auth_headers, "X-Workspace-ID": default_workspace_id}

    connection_response = await client.post(
        "/api/v1/crm/connections",
        headers=default_headers,
        json={
            "provider": "generic_rest",
            "name": "Workspace CRM Isolation",
            "environment": "development",
            "configuration": {"baseUrl": "https://example.invalid"},
        },
    )
    assert connection_response.status_code == 201, connection_response.text
    connection_id = connection_response.json()["id"]

    created_workspace = await client.post(
        "/api/v1/workspaces",
        headers=auth_headers,
        json={
            "name": "CRM Isolated Workspace",
            "slug": "crm-isolated-workspace",
            "timezone": "Asia/Kolkata",
            "defaultLanguage": "English",
            "dateFormat": "DD/MM/YYYY",
        },
    )
    assert created_workspace.status_code == 201, created_workspace.text
    isolated_workspace_id = created_workspace.json()["id"]
    isolated_headers = {**auth_headers, "X-Workspace-ID": isolated_workspace_id}

    isolated_connections = await client.get("/api/v1/crm/connections", headers=isolated_headers)
    assert isolated_connections.status_code == 200, isolated_connections.text
    assert all(item["id"] != connection_id for item in isolated_connections.json())

    forbidden_lookup = await client.get(
        f"/api/v1/crm/connections/{connection_id}",
        headers=isolated_headers,
    )
    assert forbidden_lookup.status_code == 404

    forbidden_route = await client.post(
        "/api/v1/crm/routes",
        headers=isolated_headers,
        json={
            "name": "Cross workspace route",
            "enabled": True,
            "priority": 100,
            "conditions": {},
            "connectionIds": [connection_id],
        },
    )
    assert forbidden_route.status_code == 400

    default_agent = await client.post(
        "/api/v1/agents",
        headers=default_headers,
        json={"name": "Default CRM Agent"},
    )
    assert default_agent.status_code == 201, default_agent.text
    isolated_agent = await client.post(
        "/api/v1/agents",
        headers=isolated_headers,
        json={"name": "Isolated CRM Agent"},
    )
    assert isolated_agent.status_code == 201, isolated_agent.text

    async with SessionFactory() as session:
        default_agent_row = await session.scalar(
            select(Agent).where(Agent.id == UUID(default_agent.json()["id"]))
        )
        isolated_agent_row = await session.scalar(
            select(Agent).where(Agent.id == UUID(isolated_agent.json()["id"]))
        )
        assert default_agent_row is not None
        assert isolated_agent_row is not None

        default_lead = Lead(
            tenant_id=tenant_id,
            workspace_id=UUID(default_workspace_id),
            agent_id=default_agent_row.id,
            name="Default Workspace Lead",
            status="new",
            consent=False,
            fields_json={},
        )
        isolated_lead = Lead(
            tenant_id=tenant_id,
            workspace_id=UUID(isolated_workspace_id),
            agent_id=isolated_agent_row.id,
            name="Isolated Workspace Lead",
            status="new",
            consent=False,
            fields_json={},
        )
        session.add_all([default_lead, isolated_lead])
        await session.flush()

        default_deliveries = await workspace_crm_route_service.create_deliveries(
            session,
            tenant_id=tenant_id,
            lead_id=default_lead.id,
            correlation_id="workspace-crm-default",
        )
        isolated_deliveries = await workspace_crm_route_service.create_deliveries(
            session,
            tenant_id=tenant_id,
            lead_id=isolated_lead.id,
            correlation_id="workspace-crm-isolated",
        )
        assert len(default_deliveries) == 1
        assert isolated_deliveries == []
        await session.rollback()
