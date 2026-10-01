from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
from httpx import AsyncClient

from northstar_api.database import SessionFactory
from northstar_api.education_conversation_context import EducationConversationContext
from northstar_api.education_student_activity import EducationStudentActivityEvent
from northstar_api.models import Agent, Channel, Conversation, ConversationState
from northstar_api.services.education_student_detail import enrollment_access_state


async def _seed_detail_domain(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> tuple[dict[str, str], dict[str, str]]:
    workspace = await client.get("/api/v1/workspace", headers=auth_headers)
    assert workspace.status_code == 200, workspace.text
    headers = {**auth_headers, "X-Workspace-ID": workspace.json()["id"]}
    seed = uuid.uuid4().hex[:8].upper()

    course = await client.post(
        "/api/v1/education/courses",
        headers=headers,
        json={"code": f"DETAIL-{seed}", "name": f"Detail Course {seed}"},
    )
    assert course.status_code == 201, course.text
    batch = await client.post(
        "/api/v1/education/batches",
        headers=headers,
        json={
            "courseId": course.json()["id"],
            "code": f"DETAIL-{seed}-A",
            "name": f"Detail Batch {seed}",
            "startsOn": "2026-01-01",
            "endsOn": "2027-12-31",
        },
    )
    assert batch.status_code == 201, batch.text
    agent = await client.post(
        "/api/v1/agents",
        headers=headers,
        json={
            "name": f"Detail Agent {seed}",
            "description": "Student detail regression Agent",
            "purpose": "education",
            "deploymentChannel": "website",
        },
    )
    assert agent.status_code == 201, agent.text
    activated = await client.patch(
        f"/api/v1/agents/{agent.json()['id']}",
        headers=headers,
        json={"status": "active"},
    )
    assert activated.status_code == 200, activated.text

    student = await client.post(
        "/api/v1/education/students",
        headers=headers,
        json={
            "studentNumber": f"DETAIL-{seed}-S",
            "name": "Detail Student",
            "email": f"detail-{seed.lower()}@example.com",
            "customFields": {"language": "en"},
        },
    )
    assert student.status_code == 201, student.text
    identity = await client.post(
        f"/api/v1/education/students/{student.json()['id']}/identities",
        headers=headers,
        json={
            "identityType": "website_login",
            "identifier": f"detail-{seed.lower()}@example.com",
            "status": "verified",
            "isPrimary": True,
        },
    )
    assert identity.status_code == 201, identity.text
    enrollment = await client.post(
        "/api/v1/education/enrollments",
        headers=headers,
        json={
            "studentId": student.json()["id"],
            "courseId": course.json()["id"],
            "batchId": batch.json()["id"],
            "agentId": agent.json()["id"],
            "startsOn": "2026-01-01",
            "endsOn": "2027-12-31",
            "status": "active",
        },
    )
    assert enrollment.status_code == 201, enrollment.text
    return {
        "workspaceId": workspace.json()["id"],
        "studentId": student.json()["id"],
        "courseId": course.json()["id"],
        "courseName": course.json()["name"],
        "batchId": batch.json()["id"],
        "batchName": batch.json()["name"],
        "agentId": agent.json()["id"],
        "agentName": agent.json()["name"],
        "enrollmentId": enrollment.json()["id"],
    }, headers


@pytest.mark.anyio
async def test_student_detail_aggregates_profile_access_conversations_and_activity(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    seeded, headers = await _seed_detail_domain(client, auth_headers)
    resolved_at = datetime.now(UTC)

    async with SessionFactory() as session:
        agent = await session.get(Agent, uuid.UUID(seeded["agentId"]))
        assert agent is not None
        conversation = Conversation(
            tenant_id=agent.tenant_id,
            workspace_id=uuid.UUID(seeded["workspaceId"]),
            agent_id=agent.id,
            visitor_id="detail-student",
            visitor_name="Detail Student",
            visitor_email="detail@example.com",
            channel=Channel.WIDGET,
            state=ConversationState.RESOLVED,
            resolution="answered",
            ended_at=resolved_at,
        )
        session.add(conversation)
        await session.flush()
        context = EducationConversationContext(
            tenant_id=agent.tenant_id,
            workspace_id=uuid.UUID(seeded["workspaceId"]),
            conversation_id=conversation.id,
            agent_id=agent.id,
            student_id=uuid.UUID(seeded["studentId"]),
            enrollment_id=uuid.UUID(seeded["enrollmentId"]),
            course_id=uuid.UUID(seeded["courseId"]),
            batch_id=uuid.UUID(seeded["batchId"]),
        )
        activity = EducationStudentActivityEvent(
            tenant_id=agent.tenant_id,
            workspace_id=uuid.UUID(seeded["workspaceId"]),
            student_id=uuid.UUID(seeded["studentId"]),
            enrollment_id=uuid.UUID(seeded["enrollmentId"]),
            course_id=uuid.UUID(seeded["courseId"]),
            batch_id=uuid.UUID(seeded["batchId"]),
            agent_id=agent.id,
            conversation_id=conversation.id,
            event_type="education.conversation.resolved.v1",
            resolved_at=resolved_at,
            resolution="answered",
            details_json={"topics": ["exam registration"], "messageCount": 4},
        )
        session.add_all([context, activity])
        await session.commit()

    response = await client.get(
        f"/api/v1/education/students/{seeded['studentId']}/detail",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["student"]["name"] == "Detail Student"
    assert body["summary"]["verifiedIdentityCount"] == 1
    assert body["summary"]["activeAccessCount"] == 1
    assert body["summary"]["conversationCount"] == 1
    assert body["summary"]["activityCount"] == 1
    assert body["enrollments"][0]["courseName"] == seeded["courseName"]
    assert body["enrollments"][0]["batchName"] == seeded["batchName"]
    assert body["enrollments"][0]["agentName"] == seeded["agentName"]
    assert body["enrollments"][0]["accessState"] == "active"
    assert body["conversations"][0]["state"] == "resolved"
    assert body["activity"][0]["eventType"] == "education.conversation.resolved.v1"
    assert body["activity"][0]["details"]["topics"] == ["exam registration"]


@pytest.mark.anyio
async def test_student_detail_is_workspace_scoped(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    _, headers = await _seed_detail_domain(client, auth_headers)
    response = await client.get(
        f"/api/v1/education/students/{uuid.uuid4()}/detail",
        headers=headers,
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Student not found"


def test_enrollment_access_state_respects_status_and_date_window() -> None:
    today = date(2026, 9, 11)
    assert enrollment_access_state("active", date(2026, 1, 1), date(2027, 1, 1), today=today) == "active"
    assert enrollment_access_state("active", date(2026, 10, 1), None, today=today) == "scheduled"
    assert enrollment_access_state("active", None, date(2026, 8, 31), today=today) == "expired"
    assert enrollment_access_state("suspended", None, None, today=today) == "suspended"
    assert enrollment_access_state("revoked", None, None, today=today) == "revoked"
