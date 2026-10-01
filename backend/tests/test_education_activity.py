from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from northstar_api.database import SessionFactory
from northstar_api.education_student_activity import EducationStudentActivityEvent
from northstar_api.models import Agent, Channel, Conversation, ConversationState


async def _create_education_agent(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    seed: str,
) -> str:
    response = await client.post(
        "/api/v1/agents",
        headers=headers,
        json={
            "name": f"Activity Agent {seed}",
            "description": "Education activity regression Agent",
            "purpose": "education",
            "deploymentChannel": "website",
        },
    )
    assert response.status_code == 201, response.text
    agent_id = response.json()["id"]
    activated = await client.patch(
        f"/api/v1/agents/{agent_id}",
        headers=headers,
        json={"status": "active"},
    )
    assert activated.status_code == 200, activated.text
    return agent_id


async def _create_scope(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    seed: str,
    agent_id: str,
) -> dict[str, str]:
    course = await client.post(
        "/api/v1/education/courses",
        headers=headers,
        json={"code": f"ACT-{seed}", "name": f"Activity Course {seed}"},
    )
    assert course.status_code == 201, course.text
    batch = await client.post(
        "/api/v1/education/batches",
        headers=headers,
        json={
            "courseId": course.json()["id"],
            "code": f"ACT-{seed}-B",
            "name": f"Activity Batch {seed}",
        },
    )
    assert batch.status_code == 201, batch.text
    student = await client.post(
        "/api/v1/education/students",
        headers=headers,
        json={
            "studentNumber": f"ACT-{seed}-S",
            "name": f"Activity Student {seed}",
            "email": f"activity-{seed.lower()}@example.com",
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
        "courseCode": course.json()["code"],
        "batchId": batch.json()["id"],
        "studentId": student.json()["id"],
        "studentNumber": student.json()["studentNumber"],
        "studentName": student.json()["name"],
        "enrollmentId": enrollment.json()["id"],
    }


async def _store_activity(
    *,
    workspace_id: str,
    agent_id: str,
    scope: dict[str, str],
    seed: str,
    event_type: str,
    resolution: str,
) -> dict[str, str]:
    async with SessionFactory() as session:
        agent = await session.get(Agent, uuid.UUID(agent_id))
        assert agent is not None
        conversation = Conversation(
            tenant_id=agent.tenant_id,
            workspace_id=uuid.UUID(workspace_id),
            agent_id=agent.id,
            visitor_id=f"activity-{seed.lower()}",
            visitor_name=scope["studentName"],
            visitor_email=f"activity-{seed.lower()}@example.com",
            channel=Channel.WIDGET,
            state=ConversationState.RESOLVED,
            resolution=resolution,
        )
        session.add(conversation)
        await session.flush()
        resolved_at = datetime.now(timezone.utc)
        event = EducationStudentActivityEvent(
            tenant_id=agent.tenant_id,
            workspace_id=uuid.UUID(workspace_id),
            student_id=uuid.UUID(scope["studentId"]),
            enrollment_id=uuid.UUID(scope["enrollmentId"]),
            course_id=uuid.UUID(scope["courseId"]),
            batch_id=uuid.UUID(scope["batchId"]),
            agent_id=agent.id,
            conversation_id=conversation.id,
            event_type=event_type,
            resolved_at=resolved_at,
            resolution=resolution,
            details_json={"topic": f"topic-{seed.lower()}"},
        )
        session.add(event)
        await session.flush()
        result = {
            "activityId": str(event.id),
            "conversationId": str(conversation.id),
            "conversationPublicId": conversation.public_id,
        }
        await session.commit()
        return result


@pytest.mark.anyio
async def test_education_activity_filters_enrich_and_isolate_workspace(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    workspace = await client.get("/api/v1/workspace", headers=auth_headers)
    assert workspace.status_code == 200, workspace.text
    workspace_id = workspace.json()["id"]
    headers = {**auth_headers, "X-Workspace-ID": workspace_id}
    seed = uuid.uuid4().hex[:8].upper()

    agent_id = await _create_education_agent(client, headers, seed=seed)
    first = await _create_scope(client, headers, seed=f"{seed}A", agent_id=agent_id)
    second = await _create_scope(client, headers, seed=f"{seed}B", agent_id=agent_id)
    first_event = await _store_activity(
        workspace_id=workspace_id,
        agent_id=agent_id,
        scope=first,
        seed=f"{seed}A",
        event_type="conversation.resolved",
        resolution="answered",
    )
    second_event = await _store_activity(
        workspace_id=workspace_id,
        agent_id=agent_id,
        scope=second,
        seed=f"{seed}B",
        event_type="conversation.escalated",
        resolution="human_followup",
    )

    filtered = await client.get(
        "/api/v1/education/activity",
        headers=headers,
        params={
            "agent_id": agent_id,
            "course_id": first["courseId"],
            "batch_id": first["batchId"],
            "student_id": first["studentId"],
            "event_type": "conversation.resolved",
            "search": first["studentNumber"],
        },
    )
    assert filtered.status_code == 200, filtered.text
    assert filtered.json()["total"] == 1
    item = filtered.json()["items"][0]
    assert item["id"] == first_event["activityId"]
    assert item["studentId"] == first["studentId"]
    assert item["studentNumber"] == first["studentNumber"]
    assert item["courseId"] == first["courseId"]
    assert item["courseCode"] == first["courseCode"]
    assert item["batchId"] == first["batchId"]
    assert item["agentId"] == agent_id
    assert item["conversationId"] == first_event["conversationId"]
    assert item["conversationPublicId"] == first_event["conversationPublicId"]
    assert item["resolution"] == "answered"
    assert item["details"]["topic"] == f"topic-{seed.lower()}a"

    second_only = await client.get(
        "/api/v1/education/activity",
        headers=headers,
        params={"course_id": second["courseId"], "event_type": "conversation.escalated"},
    )
    assert second_only.status_code == 200, second_only.text
    assert second_only.json()["total"] == 1
    assert second_only.json()["items"][0]["id"] == second_event["activityId"]

    mismatch = await client.get(
        "/api/v1/education/activity",
        headers=headers,
        params={"course_id": first["courseId"], "student_id": second["studentId"]},
    )
    assert mismatch.status_code == 200, mismatch.text
    assert mismatch.json()["total"] == 0

    secondary_workspace = await client.post(
        "/api/v1/workspaces",
        headers=auth_headers,
        json={
            "name": f"Activity Isolation {seed}",
            "slug": f"activity-isolation-{seed.lower()}",
        },
    )
    assert secondary_workspace.status_code == 201, secondary_workspace.text
    secondary_id = secondary_workspace.json()["id"]
    secondary_headers = {**auth_headers, "X-Workspace-ID": secondary_id}
    secondary_agent = await _create_education_agent(client, secondary_headers, seed=f"{seed}X")
    secondary_scope = await _create_scope(
        client,
        secondary_headers,
        seed=f"{seed}X",
        agent_id=secondary_agent,
    )
    secondary_event = await _store_activity(
        workspace_id=secondary_id,
        agent_id=secondary_agent,
        scope=secondary_scope,
        seed=f"{seed}X",
        event_type="conversation.resolved",
        resolution="isolated",
    )

    original_activity = await client.get(
        "/api/v1/education/activity",
        headers=headers,
        params={"page_size": 100, "search": f"Activity Student {seed}"},
    )
    assert original_activity.status_code == 200, original_activity.text
    ids = {item["id"] for item in original_activity.json()["items"]}
    assert first_event["activityId"] in ids
    assert second_event["activityId"] in ids
    assert secondary_event["activityId"] not in ids

    secondary_activity = await client.get(
        "/api/v1/education/activity",
        headers=secondary_headers,
        params={"page_size": 100},
    )
    assert secondary_activity.status_code == 200, secondary_activity.text
    assert secondary_event["activityId"] in {
        item["id"] for item in secondary_activity.json()["items"]
    }
