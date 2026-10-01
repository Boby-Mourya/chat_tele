from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from northstar_api.database import SessionFactory
from northstar_api.lead_crm.models import CRMDelivery, CRMExternalReference, CRMRoute, LeadProfile
from northstar_api.lead_crm.workspace_routing import workspace_crm_route_service
from northstar_api.models import Agent, Channel, Conversation, Lead, OutboxEvent

pytestmark = pytest.mark.usefixtures("crm_test_plan")


async def seed_flow(client, auth_headers, purpose="support"):
    suffix = uuid4().hex[:8]
    response = await client.post(
        "/api/v1/agents",
        headers=auth_headers,
        json={
            "name": f"Qualified sync {suffix}",
            "purpose": purpose,
        },
    )
    assert response.status_code == 201, response.text
    async with SessionFactory() as session:
        agent = await session.get(Agent, UUID(response.json()["id"]))
        conversation = Conversation(
            tenant_id=agent.tenant_id,
            workspace_id=agent.workspace_id,
            agent_id=agent.id,
            channel=Channel.WIDGET,
            visitor_id=uuid4().hex,
            visitor_name="Qualified sync test",
            visitor_email=f"{suffix}@example.com",
        )
        session.add(conversation)
        await session.commit()
        tenant_id, workspace_id, conversation_id = agent.tenant_id, agent.workspace_id, conversation.id
    headers = {**auth_headers, "X-Workspace-ID": str(workspace_id)}
    response = await client.post(
        "/api/v1/crm/connections",
        headers=headers,
        json={
            "provider": "generic_rest",
            "name": f"Qualified sync {suffix}",
            "environment": "development",
            "configuration": {"baseUrl": "https://example.invalid"},
        },
    )
    assert response.status_code == 201, response.text
    connection_id = UUID(response.json()["id"])
    response = await client.patch(
        f"/api/v1/crm/connections/{connection_id}/workspace-settings",
        headers=headers,
        json={"auto_sync_new_leads": True, "auto_sync_updates": False},
    )
    assert response.status_code == 200, response.text
    async with SessionFactory() as session:
        routes = (await session.scalars(select(CRMRoute).where(CRMRoute.tenant_id == tenant_id))).all()
        route = next(r for r in routes if str(connection_id) in r.actions_json.get("connectionIds", []))
        route.conditions_json = {"qualificationStatus": "qualified"}
        await session.commit()
    return tenant_id, agent.id, conversation_id, connection_id, headers


async def route_latest(tenant_id, lead_id, connection_id, reason="qualification"):
    async with SessionFactory() as session:
        event = await session.scalar(
            select(OutboxEvent)
            .where(
                OutboxEvent.aggregate_id == str(lead_id),
                OutboxEvent.event_type == "lead.crm.sync.requested.v1",
                OutboxEvent.payload["reason"].as_string() == reason,
            )
            .order_by(OutboxEvent.occurred_at.desc(), OutboxEvent.id.desc())
        )
        assert event is not None, "The UI action must automatically emit a durable sync request"
        deliveries = await workspace_crm_route_service.create_deliveries(
            session,
            tenant_id=tenant_id,
            lead_id=lead_id,
            sync_reason=event.payload["reason"],
            target_connection_id=connection_id,
        )
        ids = [delivery.id for delivery in deliveries]
        await session.commit()
        return ids


@pytest.mark.parametrize("first_step", ["resolve", "qualify"])
async def test_both_steps_trigger_one_initial_delivery_in_either_order(client, auth_headers, first_step):
    tenant_id, agent_id, conversation_id, connection_id, headers = await seed_flow(client, auth_headers)
    if first_step == "resolve":
        response = await client.post(f"/api/v1/conversations/{conversation_id}/resolve", headers=headers)
        assert response.status_code == 200, response.text
        async with SessionFactory() as session:
            lead = await session.scalar(select(Lead).where(Lead.conversation_id == conversation_id))
            lead_id = lead.id
            assert lead.status == "new"
    else:
        response = await client.post(
            "/api/v1/leads",
            headers=headers,
            json={
                "agentId": str(agent_id),
                "conversationId": str(conversation_id),
                "name": "Qualified sync test",
            },
        )
        assert response.status_code == 201, response.text
        lead_id = UUID(response.json()["id"])
        response = await client.patch(
            f"/api/v1/leads/{lead_id}", headers=headers, json={"status": "qualified"}
        )
        assert response.status_code == 200, response.text
    assert await route_latest(tenant_id, lead_id, connection_id,
        "conversation_resolved" if first_step == "resolve" else "qualification") == []

    if first_step == "resolve":
        response = await client.patch(
            f"/api/v1/leads/{lead_id}", headers=headers, json={"status": "qualified"}
        )
    else:
        response = await client.post(f"/api/v1/conversations/{conversation_id}/resolve", headers=headers)
    assert response.status_code == 200, response.text
    async with SessionFactory() as session:
        profile = await session.scalar(select(LeadProfile).where(LeadProfile.lead_id == lead_id))
        assert profile.lifecycle_status == profile.qualification_status == "qualified"
        assert profile.qualified_at is not None
    deliveries = await route_latest(tenant_id, lead_id, connection_id,
        "qualification" if first_step == "resolve" else "conversation_resolved")
    assert len(deliveries) == 1
    # Retries and repeated status selection reuse the original upsert delivery.
    assert await route_latest(tenant_id, lead_id, connection_id) == deliveries
    response = await client.patch(f"/api/v1/leads/{lead_id}", headers=headers, json={"status": "qualified"})
    assert response.status_code == 200
    assert await route_latest(tenant_id, lead_id, connection_id) == deliveries
    async with SessionFactory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(CRMDelivery)
                .where(
                    CRMDelivery.lead_id == lead_id,
                    CRMDelivery.connection_id == connection_id,
                )
            )
            == 1
        )

    # Existing records continue to receive updates without creating a new record.
    async with SessionFactory() as session:
        session.add(
            CRMExternalReference(
                tenant_id=tenant_id,
                lead_id=lead_id,
                connection_id=connection_id,
                provider="generic_rest",
                object_name="Leads",
                external_id="existing-" + str(lead_id),
            )
        )
        await session.commit()
    await client.patch(f"/api/v1/conversations/{conversation_id}", headers=headers, json={"state": "open"})
    response = await client.patch(f"/api/v1/leads/{lead_id}", headers=headers, json={"status": "converted"})
    assert response.status_code == 200
    assert await route_latest(tenant_id, lead_id, connection_id, "lead_updated") == []  # Updates are disabled.
    await client.patch(
        f"/api/v1/crm/connections/{connection_id}/workspace-settings",
        headers=headers,
        json={"auto_sync_new_leads": False, "auto_sync_updates": True},
    )
    updated = await route_latest(tenant_id, lead_id, connection_id, "lead_updated")
    assert len(updated) == 1 and updated != deliveries


async def test_unqualifying_before_dispatch_blocks_initial_sync_and_clears_qualification(
    client, auth_headers
):
    tenant_id, agent_id, conversation_id, connection_id, headers = await seed_flow(client, auth_headers)
    await client.post(f"/api/v1/conversations/{conversation_id}/resolve", headers=headers)
    async with SessionFactory() as session:
        lead_id = await session.scalar(select(Lead.id).where(Lead.conversation_id == conversation_id))
    await client.patch(f"/api/v1/leads/{lead_id}", headers=headers, json={"status": "qualified"})
    await client.patch(f"/api/v1/leads/{lead_id}", headers=headers, json={"status": "unqualified"})
    async with SessionFactory() as session:
        profile = await session.scalar(select(LeadProfile).where(LeadProfile.lead_id == lead_id))
        assert profile.qualification_status == "unqualified"
        assert profile.qualified_at is None
    assert await route_latest(tenant_id, lead_id, connection_id) == []


async def test_resolved_qualified_lead_respects_disabled_auto_sync_and_manual_override(client, auth_headers):
    tenant_id, agent_id, conversation_id, connection_id, headers = await seed_flow(client, auth_headers)
    await client.post(f"/api/v1/conversations/{conversation_id}/resolve", headers=headers)
    async with SessionFactory() as session:
        lead_id = await session.scalar(select(Lead.id).where(Lead.conversation_id == conversation_id))
    await client.patch(f"/api/v1/leads/{lead_id}", headers=headers, json={"status": "qualified"})
    await client.patch(
        f"/api/v1/crm/connections/{connection_id}/workspace-settings",
        headers=headers,
        json={"auto_sync_new_leads": False},
    )
    assert await route_latest(tenant_id, lead_id, connection_id) == []
    async with SessionFactory() as session:
        manual = await workspace_crm_route_service.create_deliveries(
            session,
            tenant_id=tenant_id,
            lead_id=lead_id,
            sync_reason="manual",
            target_connection_id=connection_id,
        )
        assert len(manual) == 1


@pytest.mark.parametrize("purpose", ["support", "lead_generation"])
async def test_resolve_with_status_saves_and_routes_once(client, auth_headers, purpose):
    tenant_id, _, conversation_id, connection_id, headers = await seed_flow(client, auth_headers, purpose)
    url = f"/api/v1/conversations/{conversation_id}/resolve"
    response = await client.post(url, headers=headers, json={"leadStatus": "qualified"})
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["state"] == "resolved"
    assert saved["leadStatus"] == "qualified"
    assert saved["canUpdateLeadStatus"] is True
    lead_id = UUID(saved["leadId"])
    deliveries = await route_latest(tenant_id, lead_id, connection_id)
    assert len(deliveries) == 1
    async with SessionFactory() as session:
        profile = await session.scalar(select(LeadProfile).where(LeadProfile.lead_id == lead_id))
        assert profile.lifecycle_status == profile.qualification_status == "qualified"
        qualified_at = profile.qualified_at
        event_count = await session.scalar(select(func.count()).select_from(OutboxEvent).where(
            OutboxEvent.aggregate_id == str(lead_id)))
    for body in ({"leadStatus": "qualified"}, None):
        repeated = await client.post(url, headers=headers, json=body)
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["leadId"] == str(lead_id)
        assert repeated.json()["leadStatus"] == "qualified"
    assert await route_latest(tenant_id, lead_id, connection_id) == deliveries
    async with SessionFactory() as session:
        assert await session.scalar(select(func.count()).select_from(Lead).where(
            Lead.conversation_id == conversation_id)) == 1
        profile = await session.scalar(select(LeadProfile).where(LeadProfile.lead_id == lead_id))
        assert profile.qualified_at == qualified_at
        assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(
            OutboxEvent.aggregate_id == str(lead_id))) == event_count
    detail = await client.get(f"/api/v1/conversations/{conversation_id}", headers=headers)
    assert detail.json()["leadStatus"] == "qualified"
    listing = await client.get("/api/v1/conversations", headers=headers)
    listed = next(item for item in listing.json()["items"] if item["id"] == str(conversation_id))
    assert listed["leadId"] == str(lead_id) and listed["leadStatus"] == "qualified"


async def test_resolve_status_validation_permission_and_rollback(client, auth_headers, monkeypatch):
    from fastapi import HTTPException

    from northstar_api.lead_crm.services import lead_domain_service
    from northstar_api.security import Principal

    _, _, conversation_id, _, headers = await seed_flow(client, auth_headers)
    url = f"/api/v1/conversations/{conversation_id}/resolve"
    invalid = await client.post(url, headers=headers, json={"leadStatus": "made_up"})
    assert invalid.status_code == 422
    original_can = Principal.can
    with monkeypatch.context() as patch:
        patch.setattr(Principal, "can", lambda self, permission: permission != "leads.update" and original_can(self, permission))
        denied = await client.post(url, headers=headers, json={"leadStatus": "qualified"})
        assert denied.status_code == 403
    async def fail_status(*args, **kwargs):
        raise HTTPException(status_code=503, detail="Temporary failure")
    with monkeypatch.context() as patch:
        patch.setattr(lead_domain_service, "update_status", fail_status)
        failed = await client.post(url, headers=headers, json={"leadStatus": "qualified"})
        assert failed.status_code == 503
    async with SessionFactory() as session:
        conversation = await session.get(Conversation, conversation_id)
        assert conversation.state.value == "open" and conversation.ended_at is None
        assert await session.scalar(select(func.count()).select_from(Lead).where(
            Lead.conversation_id == conversation_id)) == 0
    # A resolver without lead-edit permission can still use the legacy action.
    with monkeypatch.context() as patch:
        patch.setattr(Principal, "can", lambda self, permission: permission != "leads.update" and original_can(self, permission))
        legacy = await client.post(url, headers=headers)
        assert legacy.status_code == 200, legacy.text
        assert legacy.json()["leadStatus"] == "new"
        assert legacy.json()["canUpdateLeadStatus"] is False


async def test_nonqualified_resolution_waits_until_qualified_in_same_header(client, auth_headers):
    tenant_id, _, conversation_id, connection_id, headers = await seed_flow(client, auth_headers)
    url = f"/api/v1/conversations/{conversation_id}/resolve"
    response = await client.post(url, headers=headers, json={"leadStatus": "contacted"})
    assert response.status_code == 200, response.text
    lead_id = UUID(response.json()["leadId"])
    assert response.json()["leadStatus"] == "contacted"
    assert await route_latest(tenant_id, lead_id, connection_id, "conversation_resolved") == []
    response = await client.post(url, headers=headers, json={"leadStatus": "qualified"})
    assert response.status_code == 200, response.text
    assert response.json()["leadId"] == str(lead_id)
    assert len(await route_latest(tenant_id, lead_id, connection_id)) == 1
