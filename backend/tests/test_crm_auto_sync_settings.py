from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from northstar_api.database import SessionFactory
from northstar_api.lead_crm.workspace_routing import workspace_crm_route_service
from northstar_api.models import Agent, Lead

pytestmark = pytest.mark.usefixtures("crm_test_plan")

async def test_workspace_crm_auto_sync_settings_are_scoped_and_enforced(
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
            "name": "CRM Auto Sync Settings",
            "environment": "development",
            "configuration": {"baseUrl": "https://example.invalid"},
        },
    )
    assert connection_response.status_code == 201, connection_response.text
    connection_id = connection_response.json()["id"]

    settings_response = await client.get(
        f"/api/v1/crm/connections/{connection_id}/workspace-settings",
        headers=default_headers,
    )
    assert settings_response.status_code == 200, settings_response.text
    assert settings_response.json()["auto_sync_new_leads"] is True
    assert settings_response.json()["auto_sync_updates"] is True

    updated_response = await client.patch(
        f"/api/v1/crm/connections/{connection_id}/workspace-settings",
        headers=default_headers,
        json={"auto_sync_new_leads": False, "auto_sync_updates": True},
    )
    assert updated_response.status_code == 200, updated_response.text
    assert updated_response.json()["auto_sync_new_leads"] is False
    assert updated_response.json()["auto_sync_updates"] is True

    empty_patch = await client.patch(
        f"/api/v1/crm/connections/{connection_id}/workspace-settings",
        headers=default_headers,
        json={},
    )
    assert empty_patch.status_code == 400

    other_workspace = await client.post(
        "/api/v1/workspaces",
        headers=auth_headers,
        json={
            "name": "CRM Auto Sync Other",
            "slug": "crm-auto-sync-other",
            "timezone": "Asia/Kolkata",
            "defaultLanguage": "English",
            "dateFormat": "DD/MM/YYYY",
        },
    )
    assert other_workspace.status_code == 201, other_workspace.text
    other_headers = {**auth_headers, "X-Workspace-ID": other_workspace.json()["id"]}
    cross_workspace_get = await client.get(
        f"/api/v1/crm/connections/{connection_id}/workspace-settings",
        headers=other_headers,
    )
    assert cross_workspace_get.status_code == 404
    cross_workspace_patch = await client.patch(
        f"/api/v1/crm/connections/{connection_id}/workspace-settings",
        headers=other_headers,
        json={"auto_sync_new_leads": True},
    )
    assert cross_workspace_patch.status_code == 404

    agent_response = await client.post(
        "/api/v1/agents",
        headers=default_headers,
        json={"name": "CRM Auto Sync Agent"},
    )
    assert agent_response.status_code == 201, agent_response.text

    async with SessionFactory() as session:
        agent = await session.scalar(select(Agent).where(Agent.id == UUID(agent_response.json()["id"])))
        assert agent is not None

        update_lead = Lead(
            tenant_id=tenant_id,
            workspace_id=UUID(default_workspace_id),
            agent_id=agent.id,
            name="Update Auto Sync Lead",
            status="new",
            consent=False,
            fields_json={},
        )
        session.add(update_lead)
        await session.flush()

        assert (
            await workspace_crm_route_service.create_deliveries(
                session,
                tenant_id=tenant_id,
                lead_id=update_lead.id,
                sync_reason="lead_created",
            )
            == []
        )
        update_deliveries = await workspace_crm_route_service.create_deliveries(
            session,
            tenant_id=tenant_id,
            lead_id=update_lead.id,
            sync_reason="lead_updated",
        )
        assert len(update_deliveries) == 1
        await session.rollback()

    disabled_updates = await client.patch(
        f"/api/v1/crm/connections/{connection_id}/workspace-settings",
        headers=default_headers,
        json={"auto_sync_updates": False},
    )
    assert disabled_updates.status_code == 200, disabled_updates.text

    async with SessionFactory() as session:
        agent = await session.scalar(select(Agent).where(Agent.id == UUID(agent_response.json()["id"])))
        assert agent is not None
        automatic_lead = Lead(
            tenant_id=tenant_id,
            workspace_id=UUID(default_workspace_id),
            agent_id=agent.id,
            name="Disabled Auto Sync Lead",
            status="new",
            consent=False,
            fields_json={},
        )
        manual_lead = Lead(
            tenant_id=tenant_id,
            workspace_id=UUID(default_workspace_id),
            agent_id=agent.id,
            name="Manual CRM Sync Lead",
            status="new",
            consent=False,
            fields_json={},
        )
        session.add_all([automatic_lead, manual_lead])
        await session.flush()

        assert (
            await workspace_crm_route_service.create_deliveries(
                session,
                tenant_id=tenant_id,
                lead_id=automatic_lead.id,
                sync_reason="lead_updated",
            )
            == []
        )
        manual_deliveries = await workspace_crm_route_service.create_deliveries(
            session,
            tenant_id=tenant_id,
            lead_id=manual_lead.id,
            sync_reason="manual",
        )
        assert len(manual_deliveries) == 1
        await session.rollback()
