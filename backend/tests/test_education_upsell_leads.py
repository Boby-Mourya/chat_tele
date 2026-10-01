from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from northstar_api.database import SessionFactory
from northstar_api.education_conversation_context import EducationConversationContext
from northstar_api.models import Agent, Channel, Conversation, ConversationState, Lead

pytestmark = pytest.mark.usefixtures("crm_test_plan")


async def _create_education_scope(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    seed: str,
) -> tuple[str, dict[str, str]]:
    agent_response = await client.post(
        "/api/v1/agents",
        headers=headers,
        json={
            "name": f"Upsell Education Agent {seed}",
            "description": "Education upsell routing regression",
            "purpose": "education",
            "deploymentChannel": "website",
        },
    )
    assert agent_response.status_code == 201, agent_response.text
    agent_id = agent_response.json()["id"]

    course = await client.post(
        "/api/v1/education/courses",
        headers=headers,
        json={"code": f"UP-{seed}", "name": f"Upsell Course {seed}"},
    )
    assert course.status_code == 201, course.text
    batch = await client.post(
        "/api/v1/education/batches",
        headers=headers,
        json={
            "courseId": course.json()["id"],
            "code": f"UP-{seed}-B",
            "name": f"Upsell Batch {seed}",
        },
    )
    assert batch.status_code == 201, batch.text
    student = await client.post(
        "/api/v1/education/students",
        headers=headers,
        json={
            "studentNumber": f"UP-{seed}-S",
            "name": f"Upsell Student {seed}",
            "email": f"upsell-{seed.lower()}@example.com",
        },
    )
    assert student.status_code == 201, student.text
    enrollment = await client.post(
        "/api/v1/education/enrollments",
        headers=headers,
        json={
            "studentId": student.json()["id"],
            "courseId": course.json()["id"],
            "batchId": batch.json()["id"],
            "agentId": agent_id,
            "status": "active",
        },
    )
    assert enrollment.status_code == 201, enrollment.text

    activated = await client.patch(
        f"/api/v1/agents/{agent_id}",
        headers=headers,
        json={"status": "active"},
    )
    assert activated.status_code == 200, activated.text

    return agent_id, {
        "studentId": student.json()["id"],
        "studentName": student.json()["name"],
        "studentEmail": student.json()["email"],
        "courseId": course.json()["id"],
        "batchId": batch.json()["id"],
        "enrollmentId": enrollment.json()["id"],
    }


async def _create_authorized_conversation(
    *,
    workspace_id: str,
    agent_id: str,
    scope: dict[str, str],
    seed: str,
) -> str:
    async with SessionFactory() as session:
        agent = await session.get(Agent, uuid.UUID(agent_id))
        assert agent is not None
        conversation = Conversation(
            tenant_id=agent.tenant_id,
            workspace_id=uuid.UUID(workspace_id),
            agent_id=agent.id,
            visitor_id=f"education-upsell-{seed.lower()}",
            visitor_name=scope["studentName"],
            visitor_email=scope["studentEmail"],
            channel=Channel.WIDGET,
        )
        session.add(conversation)
        await session.flush()
        session.add(
            EducationConversationContext(
                tenant_id=agent.tenant_id,
                workspace_id=uuid.UUID(workspace_id),
                conversation_id=conversation.id,
                agent_id=agent.id,
                student_id=uuid.UUID(scope["studentId"]),
                enrollment_id=uuid.UUID(scope["enrollmentId"]),
                course_id=uuid.UUID(scope["courseId"]),
                batch_id=uuid.UUID(scope["batchId"]),
            )
        )
        conversation_id = str(conversation.id)
        await session.commit()
        return conversation_id


async def test_authorized_education_chats_reject_legacy_upsell_and_stay_separate(client, auth_headers):
    workspace = await client.get("/api/v1/workspace", headers=auth_headers)
    workspace_id = workspace.json()["id"]
    headers = {**auth_headers, "X-Workspace-ID": workspace_id}
    agent_id, scope = await _create_education_scope(client, headers, seed=uuid.uuid4().hex[:8].upper())
    conversation_id = await _create_authorized_conversation(
        workspace_id=workspace_id, agent_id=agent_id, scope=scope, seed=uuid.uuid4().hex[:8],
    )
    enabled = await client.patch("/api/v1/education/settings/sales-routing", headers=headers, json={"createUpsellLeads": True})
    assert enabled.status_code == 409
    for endpoint in [f"/api/v1/education/conversations/{conversation_id}/resolve-sales-intent", f"/api/v1/conversations/{conversation_id}/resolve"]:
        blocked = await client.post(endpoint, headers=headers)
        assert blocked.status_code == 409, blocked.text
    async with SessionFactory() as session:
        conversation = await session.get(Conversation, uuid.UUID(conversation_id))
        assert conversation.state == ConversationState.OPEN
        assert list(await session.scalars(select(Lead).where(Lead.conversation_id == conversation.id))) == []
        # The immutable Education context still protects a historical conversation
        # even if its agent later switches purpose.
        from northstar_api.agent_purpose import AgentPurposeSetting
        setting = await session.get(AgentPurposeSetting, uuid.UUID(agent_id))
        setting.purpose = "support"
        await session.commit()
    blocked = await client.post(f"/api/v1/conversations/{conversation_id}/resolve", headers=headers)
    assert blocked.status_code == 409
    listing = await client.get("/api/v1/education/conversations", headers=headers)
    item = next(item for item in listing.json()["items"] if item["id"] == conversation_id)
    assert item["purpose"] == "education" and item["leadId"] is None
    generic = await client.get("/api/v1/conversations", headers=headers, params={"purpose": "education"})
    assert any(item["id"] == conversation_id for item in generic.json()["items"])


async def test_sales_intent_endpoint_rejects_non_education_agents(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    workspace = await client.get("/api/v1/workspace", headers=auth_headers)
    assert workspace.status_code == 200, workspace.text
    workspace_id = workspace.json()["id"]
    headers = {**auth_headers, "X-Workspace-ID": workspace_id}
    seed = uuid.uuid4().hex[:8]

    agent = await client.post(
        "/api/v1/agents",
        headers=headers,
        json={
            "name": f"Non Education Upsell {seed}",
            "purpose": "lead_generation",
            "deploymentChannel": "website",
        },
    )
    assert agent.status_code == 201, agent.text

    async with SessionFactory() as session:
        persisted_agent = await session.get(Agent, uuid.UUID(agent.json()["id"]))
        assert persisted_agent is not None
        conversation = Conversation(
            tenant_id=persisted_agent.tenant_id,
            workspace_id=persisted_agent.workspace_id,
            agent_id=persisted_agent.id,
            visitor_id=f"not-education-{seed}",
            visitor_name="Prospect",
            channel=Channel.WIDGET,
        )
        session.add(conversation)
        await session.flush()
        conversation_id = str(conversation.id)
        await session.commit()

    response = await client.post(
        f"/api/v1/education/conversations/{conversation_id}/resolve-sales-intent",
        headers=headers,
    )
    assert response.status_code == 409, response.text
    assert "only available for Education agents" in response.json()["error"]["message"]
