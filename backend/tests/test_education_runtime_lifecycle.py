from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from httpx import AsyncClient
from sqlalchemy import select

from northstar_api.database import SessionFactory
from northstar_api.education_student_identities import StudentIdentityType
from northstar_api.models import Agent
from northstar_api.services.education_runtime_authorization import (
    EducationAccessReason,
    EducationIdentityCandidate,
    authorize_education_access,
)


async def _seed_runtime_access(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> tuple[dict[str, str], dict[str, str]]:
    workspace = await client.get("/api/v1/workspace", headers=auth_headers)
    assert workspace.status_code == 200, workspace.text
    workspace_id = workspace.json()["id"]
    headers = {**auth_headers, "X-Workspace-ID": workspace_id}
    seed = uuid.uuid4().hex[:8].upper()
    phone = f"+9197{uuid.uuid4().int % 100_000_000:08d}"

    course = await client.post(
        "/api/v1/education/courses",
        headers=headers,
        json={"code": f"RUNTIME-LIFE-{seed}", "name": f"Runtime Lifecycle {seed}"},
    )
    assert course.status_code == 201, course.text
    batch = await client.post(
        "/api/v1/education/batches",
        headers=headers,
        json={
            "courseId": course.json()["id"],
            "code": f"RUNTIME-LIFE-{seed}-A",
            "name": f"Runtime Lifecycle Batch {seed}",
            "startsOn": "2026-01-01",
            "endsOn": "2027-12-31",
        },
    )
    assert batch.status_code == 201, batch.text
    student = await client.post(
        "/api/v1/education/students",
        headers=headers,
        json={"studentNumber": f"LIFE-{seed}", "name": f"Lifecycle Student {seed}"},
    )
    assert student.status_code == 201, student.text
    identity = await client.post(
        f"/api/v1/education/students/{student.json()['id']}/identities",
        headers=headers,
        json={"identityType": "whatsapp", "identifier": phone, "status": "verified"},
    )
    assert identity.status_code == 201, identity.text
    agent = await client.post(
        "/api/v1/agents",
        headers=headers,
        json={
            "name": f"Runtime Lifecycle Agent {seed}",
            "purpose": "education",
            "deploymentChannel": "website",
        },
    )
    assert agent.status_code == 201, agent.text
    enrollment = await client.post(
        "/api/v1/education/enrollments",
        headers=headers,
        json={
            "studentId": student.json()["id"],
            "courseId": course.json()["id"],
            "batchId": batch.json()["id"],
            "agentId": agent.json()["id"],
            "status": "active",
            "startsOn": "2026-01-01",
            "endsOn": "2027-12-31",
        },
    )
    assert enrollment.status_code == 201, enrollment.text
    activated = await client.patch(
        f"/api/v1/agents/{agent.json()['id']}",
        headers=headers,
        json={"status": "active"},
    )
    assert activated.status_code == 200, activated.text
    return {
        "workspaceId": workspace_id,
        "batchId": batch.json()["id"],
        "agentId": agent.json()["id"],
        "phone": phone,
    }, headers


async def _decision(seeded: dict[str, str]) -> EducationAccessReason:
    async with SessionFactory() as session:
        agent = await session.scalar(select(Agent).where(Agent.id == uuid.UUID(seeded["agentId"])))
        assert agent is not None
        decision = await authorize_education_access(
            session,
            tenant_id=agent.tenant_id,
            workspace_id=uuid.UUID(seeded["workspaceId"]),
            agent=agent,
            identity=EducationIdentityCandidate(StudentIdentityType.WHATSAPP, seeded["phone"]),
            as_of=date(2026, 9, 10),
        )
    assert decision.authorized is False
    return decision.reason


async def test_batch_window_and_deleted_agent_fail_closed(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    seeded, headers = await _seed_runtime_access(client, auth_headers)

    ended_batch = await client.patch(
        f"/api/v1/education/batches/{seeded['batchId']}",
        headers=headers,
        json={"startsOn": "2026-01-01", "endsOn": "2026-08-31"},
    )
    assert ended_batch.status_code == 200, ended_batch.text
    assert await _decision(seeded) is EducationAccessReason.BATCH_ENDED

    future_batch = await client.patch(
        f"/api/v1/education/batches/{seeded['batchId']}",
        headers=headers,
        json={"startsOn": "2026-10-01", "endsOn": "2027-12-31"},
    )
    assert future_batch.status_code == 200, future_batch.text
    assert await _decision(seeded) is EducationAccessReason.BATCH_NOT_STARTED

    restored_batch = await client.patch(
        f"/api/v1/education/batches/{seeded['batchId']}",
        headers=headers,
        json={"startsOn": "2026-01-01", "endsOn": "2027-12-31"},
    )
    assert restored_batch.status_code == 200, restored_batch.text

    async with SessionFactory() as session:
        agent = await session.scalar(select(Agent).where(Agent.id == uuid.UUID(seeded["agentId"])))
        assert agent is not None
        agent.deleted_at = datetime.now(UTC)
        await session.commit()

    assert await _decision(seeded) is EducationAccessReason.AGENT_INACTIVE
