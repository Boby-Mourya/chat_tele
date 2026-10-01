from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from northstar_api.database import SessionFactory
from northstar_api.education_conversation_context import EducationConversationContext
from northstar_api.models import Agent, Channel, Conversation, ConversationState


async def _create_course_batch_student_enrollment(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    seed: str,
    agent_id: str,
) -> dict[str, str]:
    course = await client.post(
        "/api/v1/education/courses",
        headers=headers,
        json={"code": f"FILTER-{seed}", "name": f"Filter Course {seed}"},
    )
    assert course.status_code == 201, course.text
    batch = await client.post(
        "/api/v1/education/batches",
        headers=headers,
        json={
            "courseId": course.json()["id"],
            "code": f"FILTER-{seed}-B",
            "name": f"Filter Batch {seed}",
        },
    )
    assert batch.status_code == 201, batch.text
    student = await client.post(
        "/api/v1/education/students",
        headers=headers,
        json={
            "studentNumber": f"FILTER-{seed}-S",
            "name": f"Filter Student {seed}",
            "email": f"filter-{seed.lower()}@example.com",
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
    return {
        "courseId": course.json()["id"],
        "batchId": batch.json()["id"],
        "studentId": student.json()["id"],
        "studentName": student.json()["name"],
        "enrollmentId": enrollment.json()["id"],
    }


@pytest.mark.anyio
@pytest.mark.usefixtures("crm_test_plan")
async def test_education_conversation_filters_compose_without_replacing_generic_inbox(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    workspace = await client.get("/api/v1/workspace", headers=auth_headers)
    assert workspace.status_code == 200, workspace.text
    workspace_id = workspace.json()["id"]
    headers = {**auth_headers, "X-Workspace-ID": workspace_id}
    seed = uuid.uuid4().hex[:8].upper()

    agent = await client.post(
        "/api/v1/agents",
        headers=headers,
        json={
            "name": f"Filter Agent {seed}",
            "description": "Education conversation filter regression Agent",
            "purpose": "education",
            "deploymentChannel": "website",
        },
    )
    assert agent.status_code == 201, agent.text
    agent_id = agent.json()["id"]
    first = await _create_course_batch_student_enrollment(
        client,
        headers,
        seed=f"{seed}A",
        agent_id=agent_id,
    )
    second = await _create_course_batch_student_enrollment(
        client,
        headers,
        seed=f"{seed}B",
        agent_id=agent_id,
    )

    activated = await client.patch(
        f"/api/v1/agents/{agent_id}",
        headers=headers,
        json={"status": "active"},
    )
    assert activated.status_code == 200, activated.text

    async with SessionFactory() as session:
        stored_agent = await session.get(Agent, uuid.UUID(agent_id))
        assert stored_agent is not None
        conversation_one = Conversation(
            tenant_id=stored_agent.tenant_id,
            workspace_id=uuid.UUID(workspace_id),
            agent_id=stored_agent.id,
            visitor_id=f"filter-one-{seed}",
            visitor_name=first["studentName"],
            visitor_email=f"one-{seed.lower()}@example.com",
            channel=Channel.WIDGET,
            state=ConversationState.OPEN,
        )
        conversation_two = Conversation(
            tenant_id=stored_agent.tenant_id,
            workspace_id=uuid.UUID(workspace_id),
            agent_id=stored_agent.id,
            visitor_id=f"filter-two-{seed}",
            visitor_name=second["studentName"],
            visitor_email=f"two-{seed.lower()}@example.com",
            channel=Channel.WIDGET,
            state=ConversationState.RESOLVED,
            resolution="answered",
        )
        generic_conversation = Conversation(
            tenant_id=stored_agent.tenant_id,
            workspace_id=uuid.UUID(workspace_id),
            agent_id=stored_agent.id,
            visitor_id=f"generic-{seed}",
            visitor_name=f"Generic Visitor {seed}",
            visitor_email=f"generic-{seed.lower()}@example.com",
            channel=Channel.WIDGET,
            state=ConversationState.OPEN,
        )
        session.add_all([conversation_one, conversation_two, generic_conversation])
        await session.flush()
        session.add_all(
            [
                EducationConversationContext(
                    tenant_id=stored_agent.tenant_id,
                    workspace_id=uuid.UUID(workspace_id),
                    conversation_id=conversation_one.id,
                    agent_id=stored_agent.id,
                    student_id=uuid.UUID(first["studentId"]),
                    enrollment_id=uuid.UUID(first["enrollmentId"]),
                    course_id=uuid.UUID(first["courseId"]),
                    batch_id=uuid.UUID(first["batchId"]),
                ),
                EducationConversationContext(
                    tenant_id=stored_agent.tenant_id,
                    workspace_id=uuid.UUID(workspace_id),
                    conversation_id=conversation_two.id,
                    agent_id=stored_agent.id,
                    student_id=uuid.UUID(second["studentId"]),
                    enrollment_id=uuid.UUID(second["enrollmentId"]),
                    course_id=uuid.UUID(second["courseId"]),
                    batch_id=uuid.UUID(second["batchId"]),
                ),
            ]
        )
        await session.commit()
        conversation_one_id = str(conversation_one.id)
        conversation_two_id = str(conversation_two.id)
        generic_conversation_id = str(generic_conversation.id)

    filtered = await client.get(
        "/api/v1/education/conversations",
        headers=headers,
        params={
            "agent_id": agent_id,
            "course_id": first["courseId"],
            "batch_id": first["batchId"],
            "student_id": first["studentId"],
            "state": "open",
            "search": first["studentName"],
        },
    )
    assert filtered.status_code == 200, filtered.text
    assert filtered.json()["total"] == 1
    assert [item["id"] for item in filtered.json()["items"]] == [conversation_one_id]

    second_course = await client.get(
        "/api/v1/education/conversations",
        headers=headers,
        params={"agent_id": agent_id, "course_id": second["courseId"]},
    )
    assert second_course.status_code == 200, second_course.text
    assert second_course.json()["total"] == 1
    assert second_course.json()["items"][0]["id"] == conversation_two_id

    mismatched = await client.get(
        "/api/v1/education/conversations",
        headers=headers,
        params={
            "agent_id": agent_id,
            "course_id": first["courseId"],
            "student_id": second["studentId"],
        },
    )
    assert mismatched.status_code == 200, mismatched.text
    assert mismatched.json()["total"] == 0

    generic = await client.get(
        "/api/v1/conversations",
        headers=headers,
        params={"agent_id": agent_id, "page_size": 100},
    )
    assert generic.status_code == 200, generic.text
    ids = {item["id"] for item in generic.json()["items"]}
    assert {conversation_one_id, conversation_two_id, generic_conversation_id}.issubset(ids)
