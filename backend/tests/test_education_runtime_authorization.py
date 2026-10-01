from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from northstar_api.database import SessionFactory
from northstar_api.education_student_identities import StudentIdentityType
from northstar_api.lead_crm.channels import CanonicalInboundEvent, CanonicalSender
from northstar_api.lead_crm.domain import ChannelProvider
from northstar_api.models import Agent
from northstar_api.services.education_runtime_authorization import (
    EducationAccessReason,
    EducationIdentityCandidate,
    authorize_education_access,
    consume_pending_education_question,
    identity_candidate_for_event,
)

pytestmark = pytest.mark.usefixtures("crm_test_plan")


async def _workspace_headers(client: AsyncClient, auth_headers: dict[str, str]) -> tuple[str, dict[str, str]]:
    response = await client.get("/api/v1/workspace", headers=auth_headers)
    assert response.status_code == 200, response.text
    workspace_id = response.json()["id"]
    return workspace_id, {**auth_headers, "X-Workspace-ID": workspace_id}


async def _create_course(client: AsyncClient, headers: dict[str, str], code: str) -> dict:
    response = await client.post(
        "/api/v1/education/courses",
        headers=headers,
        json={"code": code, "name": f"{code} Course"},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _create_batch(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    course_id: str,
    code: str,
) -> dict:
    response = await client.post(
        "/api/v1/education/batches",
        headers=headers,
        json={
            "courseId": course_id,
            "code": code,
            "name": f"{code} Batch",
            "startsOn": "2026-01-01",
            "endsOn": "2027-12-31",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _create_student(client: AsyncClient, headers: dict[str, str], number: str) -> dict:
    response = await client.post(
        "/api/v1/education/students",
        headers=headers,
        json={"studentNumber": number, "name": f"Student {number}"},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _create_agent(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    name: str,
    purpose: str = "education",
) -> dict:
    response = await client.post(
        "/api/v1/agents",
        headers=headers,
        json={
            "name": name,
            "description": "Education runtime authorization test agent",
            "purpose": purpose,
            "deploymentChannel": "website",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _create_identity(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    student_id: str,
    identity_type: str,
    identifier: str,
    status: str = "verified",
) -> dict:
    response = await client.post(
        f"/api/v1/education/students/{student_id}/identities",
        headers=headers,
        json={
            "identityType": identity_type,
            "identifier": identifier,
            "status": status,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _create_enrollment(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    student_id: str,
    course_id: str,
    batch_id: str,
    agent_id: str,
    status: str = "active",
    starts_on: str = "2026-01-01",
    ends_on: str = "2027-12-31",
) -> dict:
    response = await client.post(
        "/api/v1/education/enrollments",
        headers=headers,
        json={
            "studentId": student_id,
            "courseId": course_id,
            "batchId": batch_id,
            "agentId": agent_id,
            "status": status,
            "startsOn": starts_on,
            "endsOn": ends_on,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _agent(agent_id: str) -> Agent:
    async with SessionFactory() as session:
        value = await session.scalar(select(Agent).where(Agent.id == uuid.UUID(agent_id)))
        assert value is not None
        return value


def _event(
    provider: ChannelProvider, *, external_id: str | None, phone: str | None = None
) -> CanonicalInboundEvent:
    return CanonicalInboundEvent(
        event_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        provider=provider,
        connection_key=str(uuid.uuid4()),
        external_event_id="runtime-auth-event",
        event_type="message.received",
        sender=CanonicalSender(external_id=external_id, phone=phone),
        message=None,
        correlation_id="runtime-auth-correlation",
        received_at=datetime.now(UTC),
    )


def test_channel_identity_mapping_is_explicit_and_fail_closed() -> None:
    whatsapp, reason = identity_candidate_for_event(
        _event(ChannelProvider.WHATSAPP, external_id="919876543210", phone="919876543210")
    )
    assert reason is None
    assert whatsapp == EducationIdentityCandidate(StudentIdentityType.WHATSAPP, "+919876543210")

    telegram, reason = identity_candidate_for_event(_event(ChannelProvider.TELEGRAM, external_id="123456789"))
    assert reason is None
    assert telegram == EducationIdentityCandidate(StudentIdentityType.TELEGRAM, "123456789")

    website, reason = identity_candidate_for_event(
        _event(ChannelProvider.WIDGET, external_id="STUDENT.LOGIN")
    )
    assert reason is None
    assert website == EducationIdentityCandidate(StudentIdentityType.WEBSITE_LOGIN, "STUDENT.LOGIN")

    unsigned_website, reason = identity_candidate_for_event(
        _event(ChannelProvider.WIDGET, external_id="student.login"),
        allow_unsigned_widget=True,
    )
    assert unsigned_website is None
    assert reason is EducationAccessReason.UNTRUSTED_CHANNEL

    unsupported, reason = identity_candidate_for_event(
        _event(ChannelProvider.INSTAGRAM, external_id="meta-user")
    )
    assert unsupported is None
    assert reason is EducationAccessReason.UNSUPPORTED_CHANNEL

    missing, reason = identity_candidate_for_event(_event(ChannelProvider.TELEGRAM, external_id=None))
    assert missing is None
    assert reason is EducationAccessReason.IDENTITY_MISSING


async def test_verified_identity_and_valid_enrollment_authorize_access(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    workspace_id, headers = await _workspace_headers(client, auth_headers)
    course = await _create_course(client, headers, "AUTH-CPA")
    batch = await _create_batch(client, headers, course_id=course["id"], code="AUTH-CPA-A")
    student = await _create_student(client, headers, "AUTH-1001")
    agent = await _create_agent(client, headers, name="Runtime Authorization Education Agent")
    identity = await _create_identity(
        client,
        headers,
        student_id=student["id"],
        identity_type="whatsapp",
        identifier="+91 98765 40001",
    )
    enrollment = await _create_enrollment(
        client,
        headers,
        student_id=student["id"],
        course_id=course["id"],
        batch_id=batch["id"],
        agent_id=agent["id"],
    )
    activated = await client.patch(
        f"/api/v1/agents/{agent['id']}",
        headers=headers,
        json={"status": "active"},
    )
    assert activated.status_code == 200, activated.text

    agent_model = await _agent(agent["id"])
    async with SessionFactory() as session:
        decision = await authorize_education_access(
            session,
            tenant_id=agent_model.tenant_id,
            workspace_id=uuid.UUID(workspace_id),
            agent=agent_model,
            identity=EducationIdentityCandidate(StudentIdentityType.WHATSAPP, "+919876540001"),
            as_of=date(2026, 9, 10),
        )

    assert decision.authorized is True
    assert decision.reason is EducationAccessReason.AUTHORIZED
    assert str(decision.identity_id) == identity["id"]
    assert str(decision.student_id) == student["id"]
    assert str(decision.enrollment_id) == enrollment["id"]
    assert str(decision.course_id) == course["id"]
    assert str(decision.batch_id) == batch["id"]
    assert decision.event_payload()["authorized"] is True


async def test_access_denies_unverified_wrong_agent_and_invalid_date_windows(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    workspace_id, headers = await _workspace_headers(client, auth_headers)
    course = await _create_course(client, headers, "AUTH-DATES")
    batch = await _create_batch(client, headers, course_id=course["id"], code="AUTH-DATES-A")
    student = await _create_student(client, headers, "AUTH-2001")
    agent = await _create_agent(client, headers, name="Runtime Date Education Agent")
    other_agent = await _create_agent(client, headers, name="Runtime Other Education Agent")
    identity = await _create_identity(
        client,
        headers,
        student_id=student["id"],
        identity_type="telegram",
        identifier="123450001",
        status="pending",
    )
    enrollment = await _create_enrollment(
        client,
        headers,
        student_id=student["id"],
        course_id=course["id"],
        batch_id=batch["id"],
        agent_id=agent["id"],
        starts_on="2026-10-01",
        ends_on="2027-03-31",
    )
    activated = await client.patch(
        f"/api/v1/agents/{agent['id']}", headers=headers, json={"status": "active"}
    )
    assert activated.status_code == 200, activated.text

    agent_model = await _agent(agent["id"])
    async with SessionFactory() as session:
        pending_identity = await authorize_education_access(
            session,
            tenant_id=agent_model.tenant_id,
            workspace_id=uuid.UUID(workspace_id),
            agent=agent_model,
            identity=EducationIdentityCandidate(StudentIdentityType.TELEGRAM, "123450001"),
            as_of=date(2026, 9, 10),
        )
    assert pending_identity.authorized is False
    assert pending_identity.reason is EducationAccessReason.IDENTITY_NOT_VERIFIED

    verified = await client.patch(
        f"/api/v1/education/students/{student['id']}/identities/{identity['id']}",
        headers=headers,
        json={"status": "verified"},
    )
    assert verified.status_code == 200, verified.text

    async with SessionFactory() as session:
        not_started = await authorize_education_access(
            session,
            tenant_id=agent_model.tenant_id,
            workspace_id=uuid.UUID(workspace_id),
            agent=agent_model,
            identity=EducationIdentityCandidate(StudentIdentityType.TELEGRAM, "123450001"),
            as_of=date(2026, 9, 10),
        )
    assert not_started.reason is EducationAccessReason.ACCESS_NOT_STARTED

    suspended = await client.patch(
        f"/api/v1/education/enrollments/{enrollment['id']}",
        headers=headers,
        json={"status": "suspended"},
    )
    assert suspended.status_code == 200, suspended.text
    rewindowed = await client.patch(
        f"/api/v1/education/enrollments/{enrollment['id']}",
        headers=headers,
        json={"startsOn": "2025-01-01", "endsOn": "2026-08-31", "status": "active"},
    )
    assert rewindowed.status_code == 200, rewindowed.text

    async with SessionFactory() as session:
        ended = await authorize_education_access(
            session,
            tenant_id=agent_model.tenant_id,
            workspace_id=uuid.UUID(workspace_id),
            agent=agent_model,
            identity=EducationIdentityCandidate(StudentIdentityType.TELEGRAM, "123450001"),
            as_of=date(2026, 9, 10),
        )
    assert ended.reason is EducationAccessReason.ACCESS_ENDED

    other_agent_model = await _agent(other_agent["id"])
    async with SessionFactory() as session:
        wrong_agent = await authorize_education_access(
            session,
            tenant_id=other_agent_model.tenant_id,
            workspace_id=uuid.UUID(workspace_id),
            agent=other_agent_model,
            identity=EducationIdentityCandidate(StudentIdentityType.TELEGRAM, "123450001"),
            as_of=date(2026, 9, 10),
        )
    assert wrong_agent.reason is EducationAccessReason.AGENT_INACTIVE


async def test_enrollment_statuses_and_ambiguity_fail_closed(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    workspace_id, headers = await _workspace_headers(client, auth_headers)
    course = await _create_course(client, headers, "AUTH-STATUS")
    batch = await _create_batch(client, headers, course_id=course["id"], code="AUTH-STATUS-A")
    student = await _create_student(client, headers, "AUTH-3001")
    agent = await _create_agent(client, headers, name="Runtime Status Education Agent")
    await _create_identity(
        client,
        headers,
        student_id=student["id"],
        identity_type="website_login",
        identifier="student.auth3001",
    )
    enrollment = await _create_enrollment(
        client,
        headers,
        student_id=student["id"],
        course_id=course["id"],
        batch_id=batch["id"],
        agent_id=agent["id"],
        status="pending",
    )

    pending_agent = await _agent(agent["id"])
    async with SessionFactory() as session:
        inactive = await authorize_education_access(
            session,
            tenant_id=pending_agent.tenant_id,
            workspace_id=uuid.UUID(workspace_id),
            agent=pending_agent,
            identity=EducationIdentityCandidate(StudentIdentityType.WEBSITE_LOGIN, "STUDENT.AUTH3001"),
            as_of=date(2026, 9, 10),
        )
    assert inactive.reason is EducationAccessReason.AGENT_INACTIVE

    active_enrollment = await client.patch(
        f"/api/v1/education/enrollments/{enrollment['id']}",
        headers=headers,
        json={"status": "active"},
    )
    assert active_enrollment.status_code == 200, active_enrollment.text
    activated = await client.patch(
        f"/api/v1/agents/{agent['id']}", headers=headers, json={"status": "active"}
    )
    assert activated.status_code == 200, activated.text
    agent_model = await _agent(agent["id"])

    suspended = await client.patch(
        f"/api/v1/education/enrollments/{enrollment['id']}",
        headers=headers,
        json={"status": "suspended"},
    )
    assert suspended.status_code == 200, suspended.text
    async with SessionFactory() as session:
        suspended_decision = await authorize_education_access(
            session,
            tenant_id=agent_model.tenant_id,
            workspace_id=uuid.UUID(workspace_id),
            agent=agent_model,
            identity=EducationIdentityCandidate(StudentIdentityType.WEBSITE_LOGIN, "student.auth3001"),
            as_of=date(2026, 9, 10),
        )
    assert suspended_decision.reason is EducationAccessReason.ENROLLMENT_SUSPENDED

    restored = await client.patch(
        f"/api/v1/education/enrollments/{enrollment['id']}",
        headers=headers,
        json={"status": "active"},
    )
    assert restored.status_code == 200, restored.text

    course_two = await _create_course(client, headers, "AUTH-STATUS-2")
    batch_two = await _create_batch(
        client,
        headers,
        course_id=course_two["id"],
        code="AUTH-STATUS-2-A",
    )
    second = await _create_enrollment(
        client,
        headers,
        student_id=student["id"],
        course_id=course_two["id"],
        batch_id=batch_two["id"],
        agent_id=agent["id"],
    )
    assert second["status"] == "active"

    async with SessionFactory() as session:
        ambiguous = await authorize_education_access(
            session,
            tenant_id=agent_model.tenant_id,
            workspace_id=uuid.UUID(workspace_id),
            agent=agent_model,
            identity=EducationIdentityCandidate(StudentIdentityType.WEBSITE_LOGIN, "student.auth3001"),
            message="Explain revenue recognition",
            as_of=date(2026, 9, 10),
        )
        await session.commit()
    assert ambiguous.authorized is False
    assert ambiguous.reason is EducationAccessReason.ENROLLMENT_AMBIGUOUS
    assert ambiguous.enrollment_id is None

    async with SessionFactory() as session:
        selected = await authorize_education_access(
            session,
            tenant_id=agent_model.tenant_id,
            workspace_id=uuid.UUID(workspace_id),
            agent=agent_model,
            identity=EducationIdentityCandidate(StudentIdentityType.WEBSITE_LOGIN, "student.auth3001"),
            message="AUTH-STATUS-2",
            as_of=date(2026, 9, 10),
        )
        await session.commit()
        pending_question = await consume_pending_education_question(
            session,
            tenant_id=agent_model.tenant_id,
            workspace_id=uuid.UUID(workspace_id),
            agent_id=agent_model.id,
            student_id=selected.student_id,
        )
        await session.commit()
    assert selected.authorized is True
    assert selected.enrollment_id == uuid.UUID(second["id"])
    assert pending_question == "Explain revenue recognition"

    async with SessionFactory() as session:
        remembered = await authorize_education_access(
            session,
            tenant_id=agent_model.tenant_id,
            workspace_id=uuid.UUID(workspace_id),
            agent=agent_model,
            identity=EducationIdentityCandidate(StudentIdentityType.WEBSITE_LOGIN, "student.auth3001"),
            message="Explain this more simply",
            as_of=date(2026, 9, 10),
        )
    assert remembered.authorized is True
    assert remembered.enrollment_id == selected.enrollment_id

    course_three = await _create_course(client, headers, "AUTH-NOT-ENROLLED")
    async with SessionFactory() as session:
        denied_course = await authorize_education_access(
            session,
            tenant_id=agent_model.tenant_id,
            workspace_id=uuid.UUID(workspace_id),
            agent=agent_model,
            identity=EducationIdentityCandidate(StudentIdentityType.WEBSITE_LOGIN, "student.auth3001"),
            message=course_three["code"],
            as_of=date(2026, 9, 10),
        )
    assert denied_course.authorized is False
    assert denied_course.reason is EducationAccessReason.COURSE_NOT_ENROLLED
