from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from northstar_api.database import SessionFactory
from northstar_api.education_access_recovery import EducationAccessRecoveryChallenge
from northstar_api.education_enrollments import EducationEnrollment, EnrollmentStatus
from northstar_api.education_student_identities import (
    EducationStudentIdentity,
    StudentIdentityStatus,
    StudentIdentityType,
)
from northstar_api.models import Agent, OutboxEvent
from northstar_api.services.education_runtime_authorization import (
    EducationAccessReason,
    EducationIdentityCandidate,
    authorize_education_access,
)


async def _seed_recovery_student(
    client: AsyncClient,
    auth_headers: dict[str, str],
    *,
    email: str | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    workspace = await client.get("/api/v1/workspace", headers=auth_headers)
    assert workspace.status_code == 200, workspace.text
    headers = {**auth_headers, "X-Workspace-ID": workspace.json()["id"]}
    seed = uuid.uuid4().hex[:8].upper()
    student_email = email or f"recovery-{seed.lower()}@example.com"

    course = await client.post(
        "/api/v1/education/courses",
        headers=headers,
        json={"code": f"REC-{seed}", "name": f"Recovery Course {seed}"},
    )
    assert course.status_code == 201, course.text
    batch = await client.post(
        "/api/v1/education/batches",
        headers=headers,
        json={
            "courseId": course.json()["id"],
            "code": f"REC-{seed}-A",
            "name": f"Recovery Batch {seed}",
            "startsOn": "2026-01-01",
            "endsOn": "2027-12-31",
        },
    )
    assert batch.status_code == 201, batch.text
    student = await client.post(
        "/api/v1/education/students",
        headers=headers,
        json={
            "studentNumber": f"RECOVERY-{seed}",
            "name": f"Recovery Student {seed}",
            "email": student_email,
        },
    )
    assert student.status_code == 201, student.text
    agent = await client.post(
        "/api/v1/agents",
        headers=headers,
        json={
            "name": f"Recovery Education Agent {seed}",
            "description": "Education access recovery test",
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
        "workspaceId": workspace.json()["id"],
        "agentId": agent.json()["id"],
        "agentPublicId": agent.json()["publicId"],
        "studentId": student.json()["id"],
        "studentNumber": student.json()["studentNumber"],
        "studentEmail": student_email,
        "enrollmentId": enrollment.json()["id"],
    }, headers


@pytest.mark.anyio
async def test_recovery_verifies_identity_without_storing_raw_otp_and_existing_authorizer_passes(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seeded, _ = await _seed_recovery_student(client, auth_headers)
    phone = f"+9197{uuid.uuid4().int % 100_000_000:08d}"
    delivered: dict[str, str] = {}

    async def capture_email(email: str, code: str) -> None:
        delivered.update(email=email, code=code)

    monkeypatch.setattr(
        "northstar_api.routers.education_access_recovery.send_education_recovery_email",
        capture_email,
    )
    started = await client.post(
        "/api/v1/education/access-recovery/start",
        json={
            "agentPublicId": seeded["agentPublicId"],
            "studentNumber": seeded["studentNumber"],
            "email": seeded["studentEmail"],
            "identityType": "whatsapp",
            "identifier": phone,
        },
    )
    assert started.status_code == 202, started.text
    body = started.json()
    assert body["accepted"] is True
    assert body["expiresInSeconds"] == 600
    assert delivered["email"] == seeded["studentEmail"]
    assert len(delivered["code"]) == 6 and delivered["code"].isdigit()

    request_id = uuid.UUID(body["requestId"])
    async with SessionFactory() as session:
        challenge = await session.get(EducationAccessRecoveryChallenge, request_id)
        assert challenge is not None
        assert challenge.code_digest != delivered["code"]
        assert delivered["code"] not in challenge.code_digest
        assert challenge.failed_attempts == 0
        pre_identity = await session.scalar(
            select(EducationStudentIdentity).where(
                EducationStudentIdentity.workspace_id == uuid.UUID(seeded["workspaceId"]),
                EducationStudentIdentity.normalized_identifier == phone,
            )
        )
        assert pre_identity is None

    verified = await client.post(
        "/api/v1/education/access-recovery/verify",
        json={"requestId": body["requestId"], "code": delivered["code"]},
    )
    assert verified.status_code == 200, verified.text
    assert verified.json() == {"verified": True, "alreadyVerified": False}

    async with SessionFactory() as session:
        identity = await session.scalar(
            select(EducationStudentIdentity).where(
                EducationStudentIdentity.workspace_id == uuid.UUID(seeded["workspaceId"]),
                EducationStudentIdentity.identity_type == StudentIdentityType.WHATSAPP.value,
                EducationStudentIdentity.normalized_identifier == phone,
            )
        )
        assert identity is not None
        assert identity.student_id == uuid.UUID(seeded["studentId"])
        assert identity.status == StudentIdentityStatus.VERIFIED.value
        assert identity.verified_at is not None
        challenge = await session.get(EducationAccessRecoveryChallenge, request_id)
        assert challenge is not None and challenge.consumed_at is not None

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
        assert decision.student_id == uuid.UUID(seeded["studentId"])
        assert decision.enrollment_id == uuid.UUID(seeded["enrollmentId"])

        event_types = set(
            await session.scalars(
                select(OutboxEvent.event_type).where(
                    OutboxEvent.tenant_id == agent.tenant_id,
                    OutboxEvent.aggregate_id.in_([request_id, identity.id]),
                )
            )
        )
        assert "education.access_recovery.started.v1" in event_types
        assert "education.access_recovery.completed.v1" in event_types
        assert "education.student_identity.verified.v1" in event_types


@pytest.mark.anyio
async def test_recovery_start_is_enumeration_resistant_for_unknown_student(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seeded, _ = await _seed_recovery_student(client, auth_headers)
    delivered = False

    async def capture_email(email: str, code: str) -> None:
        nonlocal delivered
        delivered = True

    monkeypatch.setattr(
        "northstar_api.routers.education_access_recovery.send_education_recovery_email",
        capture_email,
    )
    before = 0
    async with SessionFactory() as session:
        before = int(await session.scalar(select(func.count(EducationAccessRecoveryChallenge.id))) or 0)

    response = await client.post(
        "/api/v1/education/access-recovery/start",
        json={
            "agentPublicId": seeded["agentPublicId"],
            "studentNumber": "UNKNOWN-STUDENT",
            "email": "unknown@example.com",
            "identityType": "whatsapp",
            "identifier": "+919911112222",
        },
    )
    assert response.status_code == 202, response.text
    assert response.json()["accepted"] is True
    assert response.json()["expiresInSeconds"] == 600
    assert delivered is False
    async with SessionFactory() as session:
        after = int(await session.scalar(select(func.count(EducationAccessRecoveryChallenge.id))) or 0)
    assert after == before


@pytest.mark.anyio
async def test_recovery_rejects_identity_hijack_without_disclosing_conflict(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, headers = await _seed_recovery_student(client, auth_headers)
    second, _ = await _seed_recovery_student(client, auth_headers)
    phone = f"+9196{uuid.uuid4().int % 100_000_000:08d}"
    existing = await client.post(
        f"/api/v1/education/students/{second['studentId']}/identities",
        headers=headers,
        json={"identityType": "whatsapp", "identifier": phone, "status": "verified"},
    )
    assert existing.status_code == 201, existing.text
    delivered = False

    async def capture_email(email: str, code: str) -> None:
        nonlocal delivered
        delivered = True

    monkeypatch.setattr(
        "northstar_api.routers.education_access_recovery.send_education_recovery_email",
        capture_email,
    )
    response = await client.post(
        "/api/v1/education/access-recovery/start",
        json={
            "agentPublicId": first["agentPublicId"],
            "studentNumber": first["studentNumber"],
            "email": first["studentEmail"],
            "identityType": "whatsapp",
            "identifier": phone,
        },
    )
    assert response.status_code == 202, response.text
    assert response.json()["accepted"] is True
    assert delivered is False
    async with SessionFactory() as session:
        owner = await session.scalar(
            select(EducationStudentIdentity).where(
                EducationStudentIdentity.workspace_id == uuid.UUID(first["workspaceId"]),
                EducationStudentIdentity.normalized_identifier == phone,
            )
        )
        assert owner is not None
        assert owner.student_id == uuid.UUID(second["studentId"])


@pytest.mark.anyio
async def test_recovery_bad_codes_are_counted_and_lock_challenge(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seeded, _ = await _seed_recovery_student(client, auth_headers)
    phone = f"+9195{uuid.uuid4().int % 100_000_000:08d}"
    delivered: dict[str, str] = {}

    async def capture_email(email: str, code: str) -> None:
        delivered["code"] = code

    monkeypatch.setattr(
        "northstar_api.routers.education_access_recovery.send_education_recovery_email",
        capture_email,
    )
    started = await client.post(
        "/api/v1/education/access-recovery/start",
        json={
            "agentPublicId": seeded["agentPublicId"],
            "studentNumber": seeded["studentNumber"],
            "email": seeded["studentEmail"],
            "identityType": "whatsapp",
            "identifier": phone,
        },
    )
    request_id = started.json()["requestId"]
    bad = "000000" if delivered["code"] != "000000" else "000001"
    for _ in range(5):
        response = await client.post(
            "/api/v1/education/access-recovery/verify",
            json={"requestId": request_id, "code": bad},
        )
        assert response.status_code == 400, response.text
        assert response.json()["detail"] == "Verification code is invalid or expired"

    correct_after_lock = await client.post(
        "/api/v1/education/access-recovery/verify",
        json={"requestId": request_id, "code": delivered["code"]},
    )
    assert correct_after_lock.status_code == 400, correct_after_lock.text
    async with SessionFactory() as session:
        challenge = await session.get(EducationAccessRecoveryChallenge, uuid.UUID(request_id))
        assert challenge is not None
        assert challenge.failed_attempts == 5
        assert challenge.consumed_at is not None


@pytest.mark.anyio
async def test_recovery_rechecks_enrollment_before_identity_linking(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seeded, _ = await _seed_recovery_student(client, auth_headers)
    phone = f"+9194{uuid.uuid4().int % 100_000_000:08d}"
    delivered: dict[str, str] = {}

    async def capture_email(email: str, code: str) -> None:
        delivered["code"] = code

    monkeypatch.setattr(
        "northstar_api.routers.education_access_recovery.send_education_recovery_email",
        capture_email,
    )
    started = await client.post(
        "/api/v1/education/access-recovery/start",
        json={
            "agentPublicId": seeded["agentPublicId"],
            "studentNumber": seeded["studentNumber"],
            "email": seeded["studentEmail"],
            "identityType": "whatsapp",
            "identifier": phone,
        },
    )
    request_id = started.json()["requestId"]
    async with SessionFactory() as session:
        enrollment = await session.get(EducationEnrollment, uuid.UUID(seeded["enrollmentId"]))
        assert enrollment is not None
        enrollment.status = EnrollmentStatus.REVOKED.value
        await session.commit()

    verification = await client.post(
        "/api/v1/education/access-recovery/verify",
        json={"requestId": request_id, "code": delivered["code"]},
    )
    assert verification.status_code == 400, verification.text
    async with SessionFactory() as session:
        identity = await session.scalar(
            select(EducationStudentIdentity).where(
                EducationStudentIdentity.workspace_id == uuid.UUID(seeded["workspaceId"]),
                EducationStudentIdentity.normalized_identifier == phone,
            )
        )
        challenge = await session.get(EducationAccessRecoveryChallenge, uuid.UUID(request_id))
        assert identity is None
        assert challenge is not None and challenge.consumed_at is not None


@pytest.mark.anyio
async def test_recovery_expired_challenge_cannot_verify(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seeded, _ = await _seed_recovery_student(client, auth_headers)
    phone = f"+9193{uuid.uuid4().int % 100_000_000:08d}"
    delivered: dict[str, str] = {}

    async def capture_email(email: str, code: str) -> None:
        delivered["code"] = code

    monkeypatch.setattr(
        "northstar_api.routers.education_access_recovery.send_education_recovery_email",
        capture_email,
    )
    started = await client.post(
        "/api/v1/education/access-recovery/start",
        json={
            "agentPublicId": seeded["agentPublicId"],
            "studentNumber": seeded["studentNumber"],
            "email": seeded["studentEmail"],
            "identityType": "whatsapp",
            "identifier": phone,
        },
    )
    request_id = uuid.UUID(started.json()["requestId"])
    async with SessionFactory() as session:
        challenge = await session.get(EducationAccessRecoveryChallenge, request_id)
        assert challenge is not None
        challenge.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()

    response = await client.post(
        "/api/v1/education/access-recovery/verify",
        json={"requestId": str(request_id), "code": delivered["code"]},
    )
    assert response.status_code == 400, response.text
    async with SessionFactory() as session:
        identity = await session.scalar(
            select(EducationStudentIdentity).where(
                EducationStudentIdentity.workspace_id == uuid.UUID(seeded["workspaceId"]),
                EducationStudentIdentity.normalized_identifier == phone,
            )
        )
        assert identity is None
