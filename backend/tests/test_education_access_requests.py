from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from northstar_api.database import SessionFactory
from northstar_api.education_access_requests import (
    EducationAccessRequest,
    EducationAccessRequestStatus,
)
from northstar_api.education_conversation_context import EducationConversationContext
from northstar_api.education_enrollments import EducationEnrollment, EnrollmentStatus
from northstar_api.education_student_identities import (
    EducationStudentIdentity,
    StudentIdentityStatus,
    StudentIdentityType,
)
from northstar_api.models import Agent, Conversation, Lead
from northstar_api.services.education_runtime_authorization import (
    EducationAccessReason,
    EducationIdentityCandidate,
    authorize_education_access,
)


async def _seed_access_request_student(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> tuple[dict[str, str], dict[str, str]]:
    workspace = await client.get("/api/v1/workspace", headers=auth_headers)
    assert workspace.status_code == 200, workspace.text
    headers = {**auth_headers, "X-Workspace-ID": workspace.json()["id"]}
    seed = uuid.uuid4().hex[:8].upper()
    email = f"access-{seed.lower()}@example.com"

    course = await client.post(
        "/api/v1/education/courses",
        headers=headers,
        json={"code": f"ACCESS-{seed}", "name": f"Access Course {seed}"},
    )
    assert course.status_code == 201, course.text
    batch = await client.post(
        "/api/v1/education/batches",
        headers=headers,
        json={
            "courseId": course.json()["id"],
            "code": f"ACCESS-{seed}-A",
            "name": f"Access Batch {seed}",
            "startsOn": "2026-01-01",
            "endsOn": "2027-12-31",
        },
    )
    assert batch.status_code == 201, batch.text
    student = await client.post(
        "/api/v1/education/students",
        headers=headers,
        json={
            "studentNumber": f"ACCESS-{seed}",
            "name": f"Access Student {seed}",
            "email": email,
        },
    )
    assert student.status_code == 201, student.text
    agent = await client.post(
        "/api/v1/agents",
        headers=headers,
        json={
            "name": f"Access Request Education Agent {seed}",
            "description": "Education access request review test",
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
        "studentEmail": email,
        "enrollmentId": enrollment.json()["id"],
    }, headers


async def _create_public_request(
    client: AsyncClient,
    seeded: dict[str, str],
    *,
    identifier: str,
    student_number: str | None = None,
    email: str | None = None,
) -> str:
    response = await client.post(
        "/api/v1/education/access-requests",
        json={
            "agentPublicId": seeded["agentPublicId"],
            "studentNumber": student_number or seeded["studentNumber"],
            "email": email or seeded["studentEmail"],
            "identityType": "whatsapp",
            "identifier": identifier,
            "message": "I cannot access my enrolled course.",
        },
    )
    assert response.status_code == 202, response.text
    assert response.json()["accepted"] is True
    return response.json()["requestId"]


@pytest.mark.anyio
async def test_access_request_approval_links_identity_then_existing_authorizer_passes(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    seeded, headers = await _seed_access_request_student(client, auth_headers)
    phone = f"+9188{uuid.uuid4().int % 100_000_000:08d}"
    request_id = await _create_public_request(client, seeded, identifier=phone)

    async with SessionFactory() as session:
        request = await session.get(EducationAccessRequest, uuid.UUID(request_id))
        assert request is not None
        assert request.status == EducationAccessRequestStatus.PENDING.value
        assert str(request.student_id) == seeded["studentId"]
        assert str(request.enrollment_id) == seeded["enrollmentId"]
        identity = await session.scalar(
            select(EducationStudentIdentity).where(
                EducationStudentIdentity.workspace_id == uuid.UUID(seeded["workspaceId"]),
                EducationStudentIdentity.normalized_identifier == phone,
            )
        )
        assert identity is None
        assert int(
            await session.scalar(
                select(func.count(Conversation.id)).where(
                    Conversation.workspace_id == uuid.UUID(seeded["workspaceId"]),
                    Conversation.agent_id == uuid.UUID(seeded["agentId"]),
                )
            )
            or 0
        ) == 0
        assert int(
            await session.scalar(
                select(func.count(Lead.id)).where(
                    Lead.workspace_id == uuid.UUID(seeded["workspaceId"]),
                    Lead.agent_id == uuid.UUID(seeded["agentId"]),
                )
            )
            or 0
        ) == 0
        assert int(
            await session.scalar(
                select(func.count(EducationConversationContext.id)).where(
                    EducationConversationContext.workspace_id == uuid.UUID(seeded["workspaceId"]),
                    EducationConversationContext.agent_id == uuid.UUID(seeded["agentId"]),
                )
            )
            or 0
        ) == 0

    reviewed = await client.patch(
        f"/api/v1/education/access-requests/{request_id}",
        headers=headers,
        json={"action": "approve", "note": "Enrollment verified by academy support."},
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["status"] == "approved"
    assert reviewed.json()["studentId"] == seeded["studentId"]
    assert reviewed.json()["enrollmentId"] == seeded["enrollmentId"]

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
        assert decision.enrollment_id == uuid.UUID(seeded["enrollmentId"])
        assert int(
            await session.scalar(
                select(func.count(Conversation.id)).where(Conversation.agent_id == agent.id)
            )
            or 0
        ) == 0
        assert int(
            await session.scalar(select(func.count(Lead.id)).where(Lead.agent_id == agent.id)) or 0
        ) == 0
        assert int(
            await session.scalar(
                select(func.count(EducationConversationContext.id)).where(
                    EducationConversationContext.agent_id == agent.id
                )
            )
            or 0
        ) == 0


@pytest.mark.anyio
async def test_access_request_unknown_student_is_generic_and_available_for_support_review(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    seeded, headers = await _seed_access_request_student(client, auth_headers)
    phone = f"+9187{uuid.uuid4().int % 100_000_000:08d}"
    request_id = await _create_public_request(
        client,
        seeded,
        identifier=phone,
        student_number="UNKNOWN-STUDENT",
        email="unknown-student@example.com",
    )

    response = await client.get(
        "/api/v1/education/access-requests?status=pending&search=UNKNOWN-STUDENT",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    matching = [item for item in response.json() if item["id"] == request_id]
    assert len(matching) == 1
    assert matching[0]["studentId"] is None
    assert matching[0]["enrollmentId"] is None
    assert matching[0]["status"] == "pending"


@pytest.mark.anyio
async def test_access_request_approval_cannot_hijack_another_students_identity(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    first, headers = await _seed_access_request_student(client, auth_headers)
    second, _ = await _seed_access_request_student(client, auth_headers)
    phone = f"+9186{uuid.uuid4().int % 100_000_000:08d}"
    linked = await client.post(
        f"/api/v1/education/students/{second['studentId']}/identities",
        headers=headers,
        json={"identityType": "whatsapp", "identifier": phone, "status": "verified"},
    )
    assert linked.status_code == 201, linked.text
    request_id = await _create_public_request(client, first, identifier=phone)

    reviewed = await client.patch(
        f"/api/v1/education/access-requests/{request_id}",
        headers=headers,
        json={"action": "approve"},
    )
    assert reviewed.status_code == 409, reviewed.text
    assert "another Student" in reviewed.json()["detail"]

    async with SessionFactory() as session:
        request = await session.get(EducationAccessRequest, uuid.UUID(request_id))
        owner = await session.scalar(
            select(EducationStudentIdentity).where(
                EducationStudentIdentity.workspace_id == uuid.UUID(first["workspaceId"]),
                EducationStudentIdentity.normalized_identifier == phone,
            )
        )
        assert request is not None and request.status == EducationAccessRequestStatus.PENDING.value
        assert owner is not None and owner.student_id == uuid.UUID(second["studentId"])


@pytest.mark.anyio
async def test_access_request_rechecks_enrollment_and_rejects_stale_approval(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    seeded, headers = await _seed_access_request_student(client, auth_headers)
    phone = f"+9185{uuid.uuid4().int % 100_000_000:08d}"
    request_id = await _create_public_request(client, seeded, identifier=phone)

    async with SessionFactory() as session:
        enrollment = await session.get(EducationEnrollment, uuid.UUID(seeded["enrollmentId"]))
        assert enrollment is not None
        enrollment.status = EnrollmentStatus.SUSPENDED.value
        await session.commit()

    reviewed = await client.patch(
        f"/api/v1/education/access-requests/{request_id}",
        headers=headers,
        json={"action": "approve"},
    )
    assert reviewed.status_code == 409, reviewed.text
    async with SessionFactory() as session:
        request = await session.get(EducationAccessRequest, uuid.UUID(request_id))
        identity = await session.scalar(
            select(EducationStudentIdentity).where(
                EducationStudentIdentity.workspace_id == uuid.UUID(seeded["workspaceId"]),
                EducationStudentIdentity.normalized_identifier == phone,
            )
        )
        assert request is not None and request.status == EducationAccessRequestStatus.PENDING.value
        assert identity is None


@pytest.mark.anyio
async def test_access_request_denial_is_terminal_and_does_not_change_identity(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    seeded, headers = await _seed_access_request_student(client, auth_headers)
    phone = f"+9184{uuid.uuid4().int % 100_000_000:08d}"
    pending_identity = await client.post(
        f"/api/v1/education/students/{seeded['studentId']}/identities",
        headers=headers,
        json={"identityType": "whatsapp", "identifier": phone, "status": "pending"},
    )
    assert pending_identity.status_code == 201, pending_identity.text
    request_id = await _create_public_request(client, seeded, identifier=phone)

    denied = await client.patch(
        f"/api/v1/education/access-requests/{request_id}",
        headers=headers,
        json={"action": "deny", "note": "Could not validate the support request."},
    )
    assert denied.status_code == 200, denied.text
    assert denied.json()["status"] == "denied"

    second_review = await client.patch(
        f"/api/v1/education/access-requests/{request_id}",
        headers=headers,
        json={"action": "approve"},
    )
    assert second_review.status_code == 409, second_review.text

    async with SessionFactory() as session:
        identity = await session.get(
            EducationStudentIdentity,
            uuid.UUID(pending_identity.json()["id"]),
        )
        request = await session.get(EducationAccessRequest, uuid.UUID(request_id))
        assert identity is not None and identity.status == StudentIdentityStatus.PENDING.value
        assert request is not None and request.status == EducationAccessRequestStatus.DENIED.value
