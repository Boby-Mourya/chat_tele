from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from northstar_api.database import SessionFactory
from northstar_api.education_enrollments import EducationEnrollment
from northstar_api.education_student_identities import EducationStudentIdentity, StudentIdentityStatus, StudentIdentityType
from northstar_api.education_students import EducationStudent
from northstar_api.models import Agent
from northstar_api.services.education_runtime_authorization import (
    EducationAccessReason,
    EducationIdentityCandidate,
    authorize_education_access,
)


async def _seed_import_domain(
    client: AsyncClient,
    auth_headers: dict[str, str],
    *,
    batch_starts_on: str = "2026-09-01",
    batch_ends_on: str = "2027-06-30",
    purpose: str = "education",
) -> tuple[dict[str, str], dict[str, str]]:
    workspace = await client.get("/api/v1/workspace", headers=auth_headers)
    assert workspace.status_code == 200, workspace.text
    headers = {**auth_headers, "X-Workspace-ID": workspace.json()["id"]}
    seed = uuid.uuid4().hex[:8].upper()
    course_code = f"IMP-{seed}"
    batch_code = f"IMP-{seed}-A"
    course = await client.post(
        "/api/v1/education/courses",
        headers=headers,
        json={"code": course_code, "name": f"Import Course {seed}"},
    )
    assert course.status_code == 201, course.text
    batch = await client.post(
        "/api/v1/education/batches",
        headers=headers,
        json={
            "courseId": course.json()["id"],
            "code": batch_code,
            "name": f"Import Batch {seed}",
            "startsOn": batch_starts_on,
            "endsOn": batch_ends_on,
        },
    )
    assert batch.status_code == 201, batch.text
    agent = await client.post(
        "/api/v1/agents",
        headers=headers,
        json={
            "name": f"Import Agent {seed}",
            "description": "Student import test Agent",
            "purpose": purpose,
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
    return {
        "workspaceId": workspace.json()["id"],
        "courseCode": course_code,
        "batchCode": batch_code,
        "agentId": agent.json()["id"],
        "agentPublicId": agent.json()["publicId"],
    }, headers


@pytest.mark.anyio
async def test_import_preview_then_commit_creates_students_identity_and_enrollment_atomically(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    seeded, headers = await _seed_import_domain(client, auth_headers)
    unique = uuid.uuid4().hex[:8].upper()
    phone = f"+9191{uuid.uuid4().int % 100_000_000:08d}"
    rows = [
        {
            "studentNumber": f"IMPORT-{unique}-1",
            "name": "Asha Verma",
            "email": f"asha-{unique.lower()}@example.com",
            "identityType": "whatsapp",
            "identifier": phone,
            "identityVerified": True,
            "courseCode": seeded["courseCode"],
            "batchCode": seeded["batchCode"],
            "agentPublicId": seeded["agentPublicId"],
            "enrollmentStatus": "active",
            "startsOn": "2026-09-01",
            "endsOn": "2027-06-30",
            "customFields": {"language": "en"},
        },
        {
            "studentNumber": f"IMPORT-{unique}-2",
            "name": "Ravi Kumar",
            "email": f"ravi-{unique.lower()}@example.com",
        },
    ]

    preview = await client.post(
        "/api/v1/education/students/import/preview",
        headers=headers,
        json={"rows": rows},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["totalRows"] == 2
    assert preview.json()["validRows"] == 2
    assert preview.json()["invalidRows"] == 0
    assert any("without a channel/login identity" in item for item in preview.json()["rows"][1]["warnings"])
    assert any("without an Enrollment" in item for item in preview.json()["rows"][1]["warnings"])

    committed = await client.post(
        "/api/v1/education/students/import/commit",
        headers=headers,
        json={"rows": rows},
    )
    assert committed.status_code == 200, committed.text
    body = committed.json()
    assert body["committed"] is True
    assert body["result"] == {
        "createdStudents": 2,
        "createdIdentities": 1,
        "createdEnrollments": 1,
    }

    async with SessionFactory() as session:
        first = await session.scalar(
            select(EducationStudent).where(EducationStudent.student_number == rows[0]["studentNumber"])
        )
        second = await session.scalar(
            select(EducationStudent).where(EducationStudent.student_number == rows[1]["studentNumber"])
        )
        assert first is not None and second is not None
        identity = await session.scalar(
            select(EducationStudentIdentity).where(
                EducationStudentIdentity.student_id == first.id,
                EducationStudentIdentity.identity_type == StudentIdentityType.WHATSAPP.value,
            )
        )
        assert identity is not None
        assert identity.normalized_identifier == phone
        assert identity.status == StudentIdentityStatus.VERIFIED.value
        enrollment = await session.scalar(
            select(EducationEnrollment).where(EducationEnrollment.student_id == first.id)
        )
        assert enrollment is not None
        agent = await session.get(Agent, uuid.UUID(seeded["agentId"]))
        assert agent is not None
        decision = await authorize_education_access(
            session,
            tenant_id=agent.tenant_id,
            workspace_id=agent.workspace_id,
            agent=agent,
            identity=EducationIdentityCandidate(StudentIdentityType.WHATSAPP, phone),
        )
        assert decision.authorized is True
        assert decision.reason is EducationAccessReason.AUTHORIZED
        assert decision.student_id == first.id
        assert decision.enrollment_id == enrollment.id


@pytest.mark.anyio
async def test_invalid_import_commit_is_all_or_nothing(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    _, headers = await _seed_import_domain(client, auth_headers)
    duplicate = f"DUP-{uuid.uuid4().hex[:8].upper()}"
    rows = [
        {"studentNumber": duplicate, "name": "First Student"},
        {"studentNumber": duplicate, "name": "Second Student"},
    ]
    async with SessionFactory() as session:
        before = int(await session.scalar(select(func.count(EducationStudent.id))) or 0)

    preview = await client.post(
        "/api/v1/education/students/import/preview",
        headers=headers,
        json={"rows": rows},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["invalidRows"] == 2
    assert all(
        "Student ID is duplicated inside this import" in item["errors"]
        for item in preview.json()["rows"]
    )

    committed = await client.post(
        "/api/v1/education/students/import/commit",
        headers=headers,
        json={"rows": rows},
    )
    assert committed.status_code == 200, committed.text
    assert committed.json()["committed"] is False
    assert committed.json()["result"] is None
    async with SessionFactory() as session:
        after = int(await session.scalar(select(func.count(EducationStudent.id))) or 0)
        created = await session.scalar(
            select(EducationStudent.id).where(EducationStudent.student_number == duplicate)
        )
    assert after == before
    assert created is None


@pytest.mark.anyio
async def test_import_normalizes_identity_and_warns_for_shared_email_without_rejecting_it(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    _, headers = await _seed_import_domain(client, auth_headers)
    seed = uuid.uuid4().hex[:8].upper()
    shared_email = f"guardian-{seed.lower()}@example.com"
    rows = [
        {
            "studentNumber": f"EMAIL-{seed}-1",
            "name": "Student One",
            "email": shared_email.upper(),
            "identityType": "whatsapp",
            "identifier": "0091 98765-43210",
        },
        {
            "studentNumber": f"EMAIL-{seed}-2",
            "name": "Student Two",
            "email": shared_email,
        },
    ]
    preview = await client.post(
        "/api/v1/education/students/import/preview",
        headers=headers,
        json={"rows": rows},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["invalidRows"] == 0
    assert all(
        "Email is shared by multiple rows in this import" in item["warnings"]
        for item in body["rows"]
    )
    assert body["rows"][0]["row"]["email"] == shared_email


@pytest.mark.anyio
async def test_import_allows_future_batch_but_rejects_enrollment_outside_batch_bounds(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    seeded, headers = await _seed_import_domain(
        client,
        auth_headers,
        batch_starts_on="2027-01-01",
        batch_ends_on="2027-12-31",
    )
    seed = uuid.uuid4().hex[:8].upper()
    valid_row = {
        "studentNumber": f"FUTURE-{seed}",
        "name": "Future Student",
        "courseCode": seeded["courseCode"],
        "batchCode": seeded["batchCode"],
        "agentPublicId": seeded["agentPublicId"],
        "enrollmentStatus": "pending",
        "startsOn": "2027-01-01",
        "endsOn": "2027-12-31",
    }
    valid = await client.post(
        "/api/v1/education/students/import/preview",
        headers=headers,
        json={"rows": [valid_row]},
    )
    assert valid.status_code == 200, valid.text
    assert valid.json()["invalidRows"] == 0

    invalid_row = {
        **valid_row,
        "studentNumber": f"OUTSIDE-{seed}",
        "startsOn": "2026-12-01",
        "endsOn": "2028-01-01",
    }
    invalid = await client.post(
        "/api/v1/education/students/import/preview",
        headers=headers,
        json={"rows": [invalid_row]},
    )
    assert invalid.status_code == 200, invalid.text
    errors = invalid.json()["rows"][0]["errors"]
    assert "Enrollment cannot start before the Batch starts" in errors
    assert "Enrollment cannot end after the Batch ends" in errors


@pytest.mark.anyio
async def test_import_rejects_non_education_agent_assignment(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    seeded, headers = await _seed_import_domain(client, auth_headers, purpose="support")
    row = {
        "studentNumber": f"PURPOSE-{uuid.uuid4().hex[:8].upper()}",
        "name": "Purpose Student",
        "courseCode": seeded["courseCode"],
        "batchCode": seeded["batchCode"],
        "agentPublicId": seeded["agentPublicId"],
    }
    preview = await client.post(
        "/api/v1/education/students/import/preview",
        headers=headers,
        json={"rows": [row]},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["invalidRows"] == 1
    assert "Agent must have Education purpose" in preview.json()["rows"][0]["errors"]
