from __future__ import annotations

import uuid
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from northstar_api.database import SessionFactory
from northstar_api.education_conversation_context import EducationConversationContext
from northstar_api.education_student_activity import EducationStudentActivityEvent
from northstar_api.models import Agent, Channel, Conversation, Lead, Message, MessageRole

pytestmark = pytest.mark.usefixtures("crm_test_plan")

async def _workspace_headers(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> tuple[str, dict[str, str]]:
    response = await client.get("/api/v1/workspace", headers=auth_headers)
    assert response.status_code == 200, response.text
    workspace_id = response.json()["id"]
    return workspace_id, {**auth_headers, "X-Workspace-ID": workspace_id}


async def _create_agent(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    name: str,
    purpose: str,
) -> dict:
    response = await client.post(
        "/api/v1/agents",
        headers=headers,
        json={
            "name": name,
            "description": f"Purpose-aware resolution test for {purpose}",
            "purpose": purpose,
            "deploymentChannel": "website",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _conversation_for_agent(
    *,
    agent_id: UUID,
    visitor_name: str,
    message: str,
) -> tuple[UUID, UUID, UUID]:
    async with SessionFactory() as session:
        agent = await session.scalar(select(Agent).where(Agent.id == agent_id))
        assert agent is not None
        conversation = Conversation(
            tenant_id=agent.tenant_id,
            workspace_id=agent.workspace_id,
            agent_id=agent.id,
            visitor_id=f"resolution:{uuid.uuid4().hex}",
            visitor_name=visitor_name,
            channel=Channel.WIDGET,
        )
        session.add(conversation)
        await session.flush()
        session.add(
            Message(
                tenant_id=agent.tenant_id,
                workspace_id=agent.workspace_id,
                conversation_id=conversation.id,
                sequence=1,
                role=MessageRole.USER,
                content=message,
            )
        )
        await session.commit()
        return conversation.id, agent.tenant_id, agent.workspace_id


async def test_support_resolution_keeps_conversation_without_creating_lead(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    workspace_id, headers = await _workspace_headers(client, auth_headers)
    seed = uuid.uuid4().hex[:8]
    agent = await _create_agent(
        client,
        headers,
        name=f"Support Resolution {seed}",
        purpose="support",
    )
    conversation_id, _, _ = await _conversation_for_agent(
        agent_id=UUID(agent["id"]),
        visitor_name="Support Visitor",
        message="Please help me with my account.",
    )

    resolved = await client.patch(
        f"/api/v1/conversations/{conversation_id}",
        headers=headers,
        json={"state": "resolved"},
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["state"] == "resolved"
    assert [item["content"] for item in resolved.json()["messages"]] == [
        "Please help me with my account."
    ]

    async with SessionFactory() as session:
        lead_count = int(
            await session.scalar(
                select(func.count(Lead.id)).where(Lead.conversation_id == conversation_id)
            )
            or 0
        )
    assert lead_count == 0
    assert resolved.json()["workspaceId"] == workspace_id


async def test_education_resolution_records_student_history_and_lead(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    workspace_id, headers = await _workspace_headers(client, auth_headers)
    seed = uuid.uuid4().hex[:8].upper()

    course_response = await client.post(
        "/api/v1/education/courses",
        headers=headers,
        json={"code": f"RES-{seed}", "name": f"Resolution Course {seed}"},
    )
    assert course_response.status_code == 201, course_response.text
    course = course_response.json()

    batch_response = await client.post(
        "/api/v1/education/batches",
        headers=headers,
        json={
            "courseId": course["id"],
            "code": f"RES-{seed}-A",
            "name": f"Resolution Batch {seed}",
        },
    )
    assert batch_response.status_code == 201, batch_response.text
    batch = batch_response.json()

    student_response = await client.post(
        "/api/v1/education/students",
        headers=headers,
        json={
            "studentNumber": f"RES-{seed}",
            "name": f"Resolution Student {seed}",
            "email": f"resolution-{seed.lower()}@example.com",
        },
    )
    assert student_response.status_code == 201, student_response.text
    student = student_response.json()

    agent = await _create_agent(
        client,
        headers,
        name=f"Education Resolution {seed}",
        purpose="education",
    )

    enrollment_response = await client.post(
        "/api/v1/education/enrollments",
        headers=headers,
        json={
            "studentId": student["id"],
            "courseId": course["id"],
            "batchId": batch["id"],
            "agentId": agent["id"],
            "status": "active",
        },
    )
    assert enrollment_response.status_code == 201, enrollment_response.text
    enrollment = enrollment_response.json()

    conversation_id, tenant_id, conversation_workspace_id = await _conversation_for_agent(
        agent_id=UUID(agent["id"]),
        visitor_name=student["name"],
        message="Please summarize what we covered today.",
    )
    async with SessionFactory() as session:
        session.add(
            EducationConversationContext(
                tenant_id=tenant_id,
                workspace_id=conversation_workspace_id,
                conversation_id=conversation_id,
                agent_id=UUID(agent["id"]),
                student_id=UUID(student["id"]),
                enrollment_id=UUID(enrollment["id"]),
                course_id=UUID(course["id"]),
                batch_id=UUID(batch["id"]),
            )
        )
        await session.commit()

    first = await client.post(
        f"/api/v1/conversations/{conversation_id}/resolve",
        headers=headers,
    )
    assert first.status_code == 200, first.text
    assert first.json()["state"] == "resolved"
    assert [item["content"] for item in first.json()["messages"]] == [
        "Please summarize what we covered today."
    ]

    second = await client.post(
        f"/api/v1/conversations/{conversation_id}/resolve",
        headers=headers,
    )
    assert second.status_code == 200, second.text

    async with SessionFactory() as session:
        lead_count = int(
            await session.scalar(
                select(func.count(Lead.id)).where(Lead.conversation_id == conversation_id)
            )
            or 0
        )
        activities = (
            await session.scalars(
                select(EducationStudentActivityEvent).where(
                    EducationStudentActivityEvent.conversation_id == conversation_id,
                    EducationStudentActivityEvent.event_type == "conversation.resolved",
                )
            )
        ).all()

    assert lead_count == 1
    assert len(activities) == 1
    activity = activities[0]
    assert str(activity.student_id) == student["id"]
    assert str(activity.enrollment_id) == enrollment["id"]
    assert str(activity.course_id) == course["id"]
    assert str(activity.batch_id) == batch["id"]
    assert str(activity.agent_id) == agent["id"]
    assert activity.details_json["channel"] == "widget"
    assert first.json()["workspaceId"] == workspace_id

    reopened = await client.patch(
        f"/api/v1/conversations/{conversation_id}",
        headers=headers,
        json={"state": "open"},
    )
    assert reopened.status_code == 200, reopened.text
    resolved_again = await client.post(
        f"/api/v1/conversations/{conversation_id}/resolve",
        headers=headers,
    )
    assert resolved_again.status_code == 200, resolved_again.text

    async with SessionFactory() as session:
        activity_count = int(
            await session.scalar(
                select(func.count(EducationStudentActivityEvent.id)).where(
                    EducationStudentActivityEvent.conversation_id == conversation_id,
                    EducationStudentActivityEvent.event_type == "conversation.resolved",
                )
            )
            or 0
        )
    assert activity_count == 2
