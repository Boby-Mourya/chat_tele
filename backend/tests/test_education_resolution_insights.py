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

async def test_education_resolution_persists_redacted_student_topics_across_admin_surfaces(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    workspace_response = await client.get("/api/v1/workspace", headers=auth_headers)
    assert workspace_response.status_code == 200, workspace_response.text
    workspace_id = workspace_response.json()["id"]
    headers = {**auth_headers, "X-Workspace-ID": workspace_id}
    seed = uuid.uuid4().hex[:8].upper()

    course_response = await client.post(
        "/api/v1/education/courses",
        headers=headers,
        json={"code": f"INS-{seed}", "name": f"Insights Course {seed}"},
    )
    assert course_response.status_code == 201, course_response.text
    course = course_response.json()

    batch_response = await client.post(
        "/api/v1/education/batches",
        headers=headers,
        json={
            "courseId": course["id"],
            "code": f"INS-{seed}-A",
            "name": f"Insights Batch {seed}",
        },
    )
    assert batch_response.status_code == 201, batch_response.text
    batch = batch_response.json()

    student_response = await client.post(
        "/api/v1/education/students",
        headers=headers,
        json={
            "studentNumber": f"INS-{seed}",
            "name": f"Insights Student {seed}",
            "email": f"insights-{seed.lower()}@example.com",
        },
    )
    assert student_response.status_code == 201, student_response.text
    student = student_response.json()

    agent_response = await client.post(
        "/api/v1/agents",
        headers=headers,
        json={
            "name": f"Insights Education Agent {seed}",
            "description": "Education resolution insight regression Agent",
            "purpose": "education",
            "deploymentChannel": "website",
        },
    )
    assert agent_response.status_code == 201, agent_response.text
    agent = agent_response.json()

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

    first_question = "How does consolidation work for a subsidiary?"
    sensitive_question = "Please send audit notes to learner@example.com and explain audit evidence."
    assistant_answer = "This assistant response must never become a Student topic."

    async with SessionFactory() as session:
        stored_agent = await session.scalar(select(Agent).where(Agent.id == UUID(agent["id"])))
        assert stored_agent is not None
        conversation = Conversation(
            tenant_id=stored_agent.tenant_id,
            workspace_id=stored_agent.workspace_id,
            agent_id=stored_agent.id,
            visitor_id=f"insights:{seed.lower()}",
            visitor_name=student["name"],
            channel=Channel.WIDGET,
        )
        session.add(conversation)
        await session.flush()
        session.add_all(
            [
                Message(
                    tenant_id=stored_agent.tenant_id,
                    workspace_id=stored_agent.workspace_id,
                    conversation_id=conversation.id,
                    sequence=1,
                    role=MessageRole.USER,
                    content=first_question,
                ),
                Message(
                    tenant_id=stored_agent.tenant_id,
                    workspace_id=stored_agent.workspace_id,
                    conversation_id=conversation.id,
                    sequence=2,
                    role=MessageRole.ASSISTANT,
                    content=assistant_answer,
                ),
                Message(
                    tenant_id=stored_agent.tenant_id,
                    workspace_id=stored_agent.workspace_id,
                    conversation_id=conversation.id,
                    sequence=3,
                    role=MessageRole.USER,
                    content=sensitive_question,
                ),
                Message(
                    tenant_id=stored_agent.tenant_id,
                    workspace_id=stored_agent.workspace_id,
                    conversation_id=conversation.id,
                    sequence=4,
                    role=MessageRole.USER,
                    content=first_question,
                ),
                EducationConversationContext(
                    tenant_id=stored_agent.tenant_id,
                    workspace_id=stored_agent.workspace_id,
                    conversation_id=conversation.id,
                    agent_id=stored_agent.id,
                    student_id=UUID(student["id"]),
                    enrollment_id=UUID(enrollment["id"]),
                    course_id=UUID(course["id"]),
                    batch_id=UUID(batch["id"]),
                ),
            ]
        )
        await session.commit()
        conversation_id = str(conversation.id)

    blocked = await client.post(f"/api/v1/conversations/{conversation_id}/resolve", headers=headers)
    assert blocked.status_code == 409
    # Internal education activity recording remains supported without sales leads.
    from northstar_api.services.conversation_resolution import conversation_resolution_service
    for _ in range(2):
        async with SessionFactory() as session:
            conversation = await session.get(Conversation, UUID(conversation_id))
            result = await conversation_resolution_service.resolve(session, conversation=conversation)
            assert result.lead is None
            await session.commit()

    async with SessionFactory() as session:
        lead_count = int(
            await session.scalar(
                select(func.count(Lead.id)).where(Lead.conversation_id == UUID(conversation_id))
            )
            or 0
        )
        activities = (
            await session.scalars(
                select(EducationStudentActivityEvent).where(
                    EducationStudentActivityEvent.conversation_id == UUID(conversation_id),
                    EducationStudentActivityEvent.event_type == "conversation.resolved",
                )
            )
        ).all()

    assert lead_count == 0
    assert len(activities) == 1
    details = activities[0].details_json
    assert details["studentMessageCount"] == 3
    assert details["topicsAsked"] == [
        "Please send audit notes to [REDACTED_EMAIL] and explain audit evidence.",
        first_question,
    ]
    assert assistant_answer not in " ".join(details["topicsAsked"])
    assert "learner@example.com" not in " ".join(details["topicsAsked"])

    student_detail = await client.get(
        f"/api/v1/education/students/{student['id']}/detail",
        headers=headers,
    )
    assert student_detail.status_code == 200, student_detail.text
    matching_detail = next(
        item for item in student_detail.json()["activity"] if item["conversationId"] == conversation_id
    )
    assert matching_detail["details"]["studentMessageCount"] == 3
    assert matching_detail["details"]["topicsAsked"] == details["topicsAsked"]

    activity_admin = await client.get(
        "/api/v1/education/activity",
        headers=headers,
        params={"student_id": student["id"], "search": student["studentNumber"]},
    )
    assert activity_admin.status_code == 200, activity_admin.text
    matching_admin = next(
        item for item in activity_admin.json()["items"] if item["conversationId"] == conversation_id
    )
    assert matching_admin["details"]["studentMessageCount"] == 3
    assert matching_admin["details"]["topicsAsked"] == details["topicsAsked"]
