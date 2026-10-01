from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.agent_purpose import AgentPurpose, get_agent_purpose
from northstar_api.education import CourseStatus, EducationCourse
from northstar_api.education_access_requests import (
    EducationAccessRequest,
    EducationAccessRequestStatus,
)
from northstar_api.education_batches import BatchStatus, EducationBatch
from northstar_api.education_enrollments import EducationEnrollment, EnrollmentStatus
from northstar_api.education_student_identities import (
    EducationStudentIdentity,
    StudentIdentityStatus,
    StudentIdentityType,
)
from northstar_api.education_students import EducationStudent, StudentStatus
from northstar_api.models import Agent, AgentStatus
from northstar_api.services.outbox import enqueue_event
from northstar_api.services.student_identity import normalize_student_identity


class EducationAccessRequestReviewError(RuntimeError):
    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class AccessRequestCreation:
    request: EducationAccessRequest
    matched_student: bool
    matched_enrollment: bool


def _date_valid(enrollment: EducationEnrollment, batch: EducationBatch, *, now: datetime) -> bool:
    today = now.date()
    if batch.starts_on is not None and today < batch.starts_on:
        return False
    if batch.ends_on is not None and today > batch.ends_on:
        return False
    if enrollment.starts_on is not None and today < enrollment.starts_on:
        return False
    if enrollment.ends_on is not None and today > enrollment.ends_on:
        return False
    return True


async def _education_agent(
    session: AsyncSession,
    *,
    public_id: str,
) -> Agent | None:
    agent = await session.scalar(
        select(Agent).where(
            Agent.public_id == public_id,
            Agent.status == AgentStatus.ACTIVE,
            Agent.deleted_at.is_(None),
        )
    )
    if agent is None:
        return None
    purpose = await get_agent_purpose(
        session,
        tenant_id=agent.tenant_id,
        workspace_id=agent.workspace_id,
        agent_id=agent.id,
    )
    return agent if purpose is AgentPurpose.EDUCATION else None


async def _valid_enrollments(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    agent_id: UUID,
    student_id: UUID,
) -> list[EducationEnrollment]:
    rows = (
        await session.execute(
            select(EducationEnrollment, EducationCourse, EducationBatch)
            .join(EducationCourse, EducationCourse.id == EducationEnrollment.course_id)
            .join(EducationBatch, EducationBatch.id == EducationEnrollment.batch_id)
            .where(
                EducationEnrollment.tenant_id == tenant_id,
                EducationEnrollment.workspace_id == workspace_id,
                EducationEnrollment.agent_id == agent_id,
                EducationEnrollment.student_id == student_id,
                EducationEnrollment.status == EnrollmentStatus.ACTIVE.value,
                EducationCourse.tenant_id == tenant_id,
                EducationCourse.workspace_id == workspace_id,
                EducationCourse.status == CourseStatus.ACTIVE.value,
                EducationBatch.tenant_id == tenant_id,
                EducationBatch.workspace_id == workspace_id,
                EducationBatch.course_id == EducationEnrollment.course_id,
                EducationBatch.status == BatchStatus.ACTIVE.value,
            )
            .order_by(EducationEnrollment.updated_at.desc())
        )
    ).all()
    now = datetime.now(UTC)
    return [
        enrollment
        for enrollment, _course, batch in rows
        if _date_valid(enrollment, batch, now=now)
    ]


async def create_education_access_request(
    session: AsyncSession,
    *,
    request_id: UUID,
    agent_public_id: str,
    student_number: str,
    email: str,
    identity_type: StudentIdentityType,
    identifier: str,
    message: str | None,
) -> AccessRequestCreation | None:
    """Create a human-review fallback without exposing Student/enrollment existence."""

    try:
        normalized_identifier = normalize_student_identity(identity_type, identifier)
    except ValueError:
        return None

    agent = await _education_agent(session, public_id=agent_public_id)
    if agent is None:
        return None

    normalized_email = email.strip().lower()
    student = await session.scalar(
        select(EducationStudent).where(
            EducationStudent.tenant_id == agent.tenant_id,
            EducationStudent.workspace_id == agent.workspace_id,
            EducationStudent.student_number == student_number,
            EducationStudent.email.is_not(None),
        )
    )
    if student is not None and (student.email or "").strip().lower() != normalized_email:
        student = None

    enrollment: EducationEnrollment | None = None
    if student is not None and student.status == StudentStatus.ACTIVE.value:
        candidates = await _valid_enrollments(
            session,
            tenant_id=agent.tenant_id,
            workspace_id=agent.workspace_id,
            agent_id=agent.id,
            student_id=student.id,
        )
        if len(candidates) == 1:
            enrollment = candidates[0]

    existing = await session.scalar(
        select(EducationAccessRequest)
        .where(
            EducationAccessRequest.tenant_id == agent.tenant_id,
            EducationAccessRequest.workspace_id == agent.workspace_id,
            EducationAccessRequest.agent_id == agent.id,
            EducationAccessRequest.student_number == student_number,
            EducationAccessRequest.identity_type == identity_type.value,
            EducationAccessRequest.normalized_identifier == normalized_identifier,
            EducationAccessRequest.status == EducationAccessRequestStatus.PENDING.value,
        )
        .order_by(EducationAccessRequest.created_at.desc())
        .limit(1)
    )
    if existing is not None:
        existing.email = normalized_email
        existing.message = message
        if existing.student_id is None and student is not None:
            existing.student_id = student.id
        if existing.enrollment_id is None and enrollment is not None:
            existing.enrollment_id = enrollment.id
        await session.flush()
        return AccessRequestCreation(
            request=existing,
            matched_student=existing.student_id is not None,
            matched_enrollment=existing.enrollment_id is not None,
        )

    request = EducationAccessRequest(
        id=request_id,
        tenant_id=agent.tenant_id,
        workspace_id=agent.workspace_id,
        agent_id=agent.id,
        student_id=student.id if student is not None else None,
        enrollment_id=enrollment.id if enrollment is not None else None,
        student_number=student_number,
        email=normalized_email,
        identity_type=identity_type.value,
        normalized_identifier=normalized_identifier,
        message=message,
        status=EducationAccessRequestStatus.PENDING.value,
    )
    session.add(request)
    await session.flush()
    enqueue_event(
        session,
        tenant_id=agent.tenant_id,
        aggregate_type="education_access_request",
        aggregate_id=request.id,
        event_type="education.access_request.created.v1",
        payload={
            "requestId": str(request.id),
            "workspaceId": str(agent.workspace_id),
            "agentId": str(agent.id),
            "studentId": str(request.student_id) if request.student_id else None,
            "enrollmentId": str(request.enrollment_id) if request.enrollment_id else None,
            "identityType": request.identity_type,
            "matchedStudent": request.student_id is not None,
            "matchedEnrollment": request.enrollment_id is not None,
        },
    )
    return AccessRequestCreation(
        request=request,
        matched_student=request.student_id is not None,
        matched_enrollment=request.enrollment_id is not None,
    )


async def _approval_scope(
    session: AsyncSession,
    *,
    request: EducationAccessRequest,
    student_id: UUID,
    enrollment_id: UUID,
) -> tuple[EducationStudent, EducationEnrollment]:
    student = await session.scalar(
        select(EducationStudent).where(
            EducationStudent.id == student_id,
            EducationStudent.tenant_id == request.tenant_id,
            EducationStudent.workspace_id == request.workspace_id,
        )
    )
    if student is None:
        raise EducationAccessRequestReviewError("Student not found", 404)
    if student.status != StudentStatus.ACTIVE.value:
        raise EducationAccessRequestReviewError("Reactivate the Student before approving access")

    agent = await session.scalar(
        select(Agent).where(
            Agent.id == request.agent_id,
            Agent.tenant_id == request.tenant_id,
            Agent.workspace_id == request.workspace_id,
            Agent.status == AgentStatus.ACTIVE,
            Agent.deleted_at.is_(None),
        )
    )
    if agent is None:
        raise EducationAccessRequestReviewError("Education Agent is no longer active")
    purpose = await get_agent_purpose(
        session,
        tenant_id=request.tenant_id,
        workspace_id=request.workspace_id,
        agent_id=agent.id,
    )
    if purpose is not AgentPurpose.EDUCATION:
        raise EducationAccessRequestReviewError("Agent is no longer an Education Agent")

    enrollment = await session.scalar(
        select(EducationEnrollment).where(
            EducationEnrollment.id == enrollment_id,
            EducationEnrollment.tenant_id == request.tenant_id,
            EducationEnrollment.workspace_id == request.workspace_id,
            EducationEnrollment.agent_id == request.agent_id,
            EducationEnrollment.student_id == student.id,
            EducationEnrollment.status == EnrollmentStatus.ACTIVE.value,
        )
    )
    if enrollment is None:
        raise EducationAccessRequestReviewError(
            "Select an active Enrollment for this Student and Education Agent"
        )

    course = await session.scalar(
        select(EducationCourse).where(
            EducationCourse.id == enrollment.course_id,
            EducationCourse.tenant_id == request.tenant_id,
            EducationCourse.workspace_id == request.workspace_id,
            EducationCourse.status == CourseStatus.ACTIVE.value,
        )
    )
    batch = await session.scalar(
        select(EducationBatch).where(
            EducationBatch.id == enrollment.batch_id,
            EducationBatch.course_id == enrollment.course_id,
            EducationBatch.tenant_id == request.tenant_id,
            EducationBatch.workspace_id == request.workspace_id,
            EducationBatch.status == BatchStatus.ACTIVE.value,
        )
    )
    if course is None or batch is None or not _date_valid(enrollment, batch, now=datetime.now(UTC)):
        raise EducationAccessRequestReviewError(
            "Course, Batch, or Enrollment access is no longer active"
        )
    return student, enrollment


async def _verify_identity_for_request(
    session: AsyncSession,
    *,
    request: EducationAccessRequest,
    student: EducationStudent,
) -> tuple[EducationStudentIdentity, bool]:
    identity = await session.scalar(
        select(EducationStudentIdentity)
        .where(
            EducationStudentIdentity.tenant_id == request.tenant_id,
            EducationStudentIdentity.workspace_id == request.workspace_id,
            EducationStudentIdentity.identity_type == request.identity_type,
            EducationStudentIdentity.normalized_identifier == request.normalized_identifier,
        )
        .with_for_update()
    )
    if identity is not None and identity.student_id != student.id:
        raise EducationAccessRequestReviewError(
            "This identity is already linked to another Student in this workspace"
        )
    if identity is not None and identity.status == StudentIdentityStatus.REVOKED.value:
        raise EducationAccessRequestReviewError(
            "This identity was revoked. Restore it from Student identities before approval"
        )
    if identity is not None:
        changed = identity.status != StudentIdentityStatus.VERIFIED.value
        if changed:
            identity.status = StudentIdentityStatus.VERIFIED.value
            identity.verified_at = datetime.now(UTC)
            await session.flush()
        return identity, changed

    has_other = await session.scalar(
        select(EducationStudentIdentity.id).where(
            EducationStudentIdentity.student_id == student.id,
            EducationStudentIdentity.identity_type == request.identity_type,
            EducationStudentIdentity.status != StudentIdentityStatus.REVOKED.value,
        )
    )
    candidate = EducationStudentIdentity(
        tenant_id=request.tenant_id,
        workspace_id=request.workspace_id,
        student_id=student.id,
        identity_type=request.identity_type,
        identifier=request.normalized_identifier,
        normalized_identifier=request.normalized_identifier,
        label="Verified by access-request review",
        status=StudentIdentityStatus.VERIFIED.value,
        is_primary=has_other is None,
        verified_at=datetime.now(UTC),
    )
    try:
        async with session.begin_nested():
            session.add(candidate)
            await session.flush()
        return candidate, True
    except IntegrityError:
        identity = await session.scalar(
            select(EducationStudentIdentity).where(
                EducationStudentIdentity.tenant_id == request.tenant_id,
                EducationStudentIdentity.workspace_id == request.workspace_id,
                EducationStudentIdentity.identity_type == request.identity_type,
                EducationStudentIdentity.normalized_identifier == request.normalized_identifier,
            )
        )
        if identity is None or identity.student_id != student.id:
            raise EducationAccessRequestReviewError(
                "This identity was linked to another Student while the request was reviewed"
            ) from None
        if identity.status == StudentIdentityStatus.REVOKED.value:
            raise EducationAccessRequestReviewError(
                "This identity was revoked while the request was reviewed"
            ) from None
        changed = identity.status != StudentIdentityStatus.VERIFIED.value
        if changed:
            identity.status = StudentIdentityStatus.VERIFIED.value
            identity.verified_at = datetime.now(UTC)
            await session.flush()
        return identity, changed


async def review_education_access_request(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    request_id: UUID,
    reviewer_user_id: UUID,
    action: str,
    student_id: UUID | None,
    enrollment_id: UUID | None,
    note: str | None,
) -> EducationAccessRequest:
    request = await session.scalar(
        select(EducationAccessRequest)
        .where(
            EducationAccessRequest.id == request_id,
            EducationAccessRequest.tenant_id == tenant_id,
            EducationAccessRequest.workspace_id == workspace_id,
        )
        .with_for_update()
    )
    if request is None:
        raise EducationAccessRequestReviewError("Access request not found", 404)
    if request.status != EducationAccessRequestStatus.PENDING.value:
        raise EducationAccessRequestReviewError("Access request has already been reviewed")

    now = datetime.now(UTC)
    if action == "deny":
        request.status = EducationAccessRequestStatus.DENIED.value
        request.reviewed_by_user_id = reviewer_user_id
        request.reviewed_at = now
        request.resolution_note = note
        enqueue_event(
            session,
            tenant_id=tenant_id,
            aggregate_type="education_access_request",
            aggregate_id=request.id,
            event_type="education.access_request.denied.v1",
            payload={
                "requestId": str(request.id),
                "workspaceId": str(workspace_id),
                "agentId": str(request.agent_id),
                "studentId": str(request.student_id) if request.student_id else None,
                "reviewedBy": str(reviewer_user_id),
            },
        )
        await session.flush()
        return request

    if action != "approve":
        raise EducationAccessRequestReviewError("Unsupported access request action", 422)

    selected_student_id = student_id or request.student_id
    selected_enrollment_id = enrollment_id or request.enrollment_id
    if selected_student_id is None or selected_enrollment_id is None:
        raise EducationAccessRequestReviewError(
            "Select a Student and active Enrollment before approving this request",
            422,
        )

    student, enrollment = await _approval_scope(
        session,
        request=request,
        student_id=selected_student_id,
        enrollment_id=selected_enrollment_id,
    )
    identity, identity_changed = await _verify_identity_for_request(
        session,
        request=request,
        student=student,
    )

    request.student_id = student.id
    request.enrollment_id = enrollment.id
    request.status = EducationAccessRequestStatus.APPROVED.value
    request.reviewed_by_user_id = reviewer_user_id
    request.reviewed_at = now
    request.resolution_note = note

    if identity_changed:
        enqueue_event(
            session,
            tenant_id=tenant_id,
            aggregate_type="education_student_identity",
            aggregate_id=identity.id,
            event_type="education.student_identity.verified.v1",
            payload={
                "identityId": str(identity.id),
                "studentId": str(student.id),
                "workspaceId": str(workspace_id),
                "identityType": identity.identity_type,
                "source": "access_request_approval",
            },
        )
    enqueue_event(
        session,
        tenant_id=tenant_id,
        aggregate_type="education_access_request",
        aggregate_id=request.id,
        event_type="education.access_request.approved.v1",
        payload={
            "requestId": str(request.id),
            "workspaceId": str(workspace_id),
            "agentId": str(request.agent_id),
            "studentId": str(student.id),
            "enrollmentId": str(enrollment.id),
            "identityId": str(identity.id),
            "reviewedBy": str(reviewer_user_id),
        },
    )
    await session.flush()
    return request
