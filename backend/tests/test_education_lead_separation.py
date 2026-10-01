from uuid import UUID

import pytest
from sqlalchemy import select
from test_resolved_qualified_crm_sync import seed_flow

from northstar_api.database import SessionFactory
from northstar_api.lead_crm.models import CRMDelivery
from northstar_api.lead_crm.services import lead_domain_service
from northstar_api.lead_crm.workspace_routing import workspace_crm_route_service
from northstar_api.models import Conversation, Lead, Message, MessageRole
from northstar_api.workers.crm_delivery_worker import process_delivery

pytestmark = pytest.mark.usefixtures("crm_test_plan")


async def test_education_inbox_cannot_resolve_or_create_leads(client, auth_headers):
    tenant, agent_id, conversation_id, _, headers = await seed_flow(client, auth_headers, "education")
    async with SessionFactory() as session:
        conversation = await session.get(Conversation, conversation_id)
        session.add(
            Message(
                tenant_id=tenant,
                workspace_id=conversation.workspace_id,
                conversation_id=conversation_id,
                sequence=1,
                role=MessageRole.USER,
                content="Explain accounting",
            )
        )
        await session.commit()
    for payload in (None, {"leadStatus": "qualified"}):
        response = await client.post(
            f"/api/v1/conversations/{conversation_id}/resolve", headers=headers, json=payload
        )
        assert response.status_code == 409, response.text
    patch = await client.patch(
        f"/api/v1/conversations/{conversation_id}", headers=headers, json={"state": "resolved"}
    )
    assert patch.status_code == 409
    manual_lead = await client.post(
        "/api/v1/leads",
        headers=headers,
        json={"agentId": str(agent_id), "conversationId": str(conversation_id)},
    )
    assert manual_lead.status_code == 409
    detail = await client.get(f"/api/v1/conversations/{conversation_id}", headers=headers)
    assert detail.json()["state"] == "open"
    assert detail.json()["messages"][0]["content"] == "Explain accounting"
    assert detail.json()["purpose"] == "education"
    assert detail.json()["leadId"] is None and detail.json()["canUpdateLeadStatus"] is False
    async with SessionFactory() as session:
        assert await session.scalar(select(Lead.id).where(Lead.conversation_id == conversation_id)) is None
    education = await client.get("/api/v1/conversations", headers=headers, params={"purpose": "education"})
    assert any(item["id"] == str(conversation_id) for item in education.json()["items"])
    support = await client.get("/api/v1/conversations", headers=headers, params={"purpose": "support"})
    assert all(item["id"] != str(conversation_id) for item in support.json()["items"])


async def test_legacy_education_lead_hidden_from_lists_exports_and_crm_retries(client, auth_headers):
    tenant, agent_id, conversation_id, connection_id, headers = await seed_flow(
        client, auth_headers, "education"
    )
    async with SessionFactory() as session:
        conversation = await session.get(Conversation, conversation_id)
        lead = Lead(
            tenant_id=tenant,
            workspace_id=conversation.workspace_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
            name="Historical education contact",
            status="qualified",
        )
        session.add(lead)
        await session.flush()
        lead_id = lead.id
        await lead_domain_service.ensure_profile(session, lead=lead)
        delivery = CRMDelivery(
            tenant_id=tenant,
            lead_id=lead_id,
            connection_id=connection_id,
            provider="generic_rest",
            operation="upsert",
            status="queued",
            idempotency_key=f"education-{lead_id}",
        )
        session.add(delivery)
        await session.commit()
        delivery_id = delivery.id
    leads = await client.get("/api/v1/leads", headers=headers, params={"agent_id": str(agent_id)})
    assert leads.json()["items"] == [] and leads.json()["total"] == 0
    exported = await client.get("/api/v1/leads/layout/export?format=csv", headers=headers)
    assert exported.status_code == 200
    assert "Historical education contact" not in exported.text
    patch = await client.patch(f"/api/v1/leads/{lead_id}", headers=headers, json={"status": "qualified"})
    assert patch.status_code == 404
    sync = await client.post(f"/api/v1/leads/{lead_id}/sync", headers=headers, json={"reason": "manual"})
    assert sync.status_code == 404, sync.text
    detail = await client.get(f"/api/v1/conversations/{conversation_id}", headers=headers)
    assert detail.json()["leadId"] is None and detail.json()["state"] == "open"
    async with SessionFactory() as session:
        for reason in ["qualification", "manual", "lead_created"]:
            assert (
                await workspace_crm_route_service.create_deliveries(
                    session, tenant_id=tenant, lead_id=lead_id, sync_reason=reason
                )
                == []
            )
        await process_delivery(session, delivery_id)
        delivery = await session.get(CRMDelivery, delivery_id)
        assert delivery.status == "cancelled" and delivery.attempt_count == 0
        assert await session.get(Conversation, UUID(detail.json()["id"])) is not None
