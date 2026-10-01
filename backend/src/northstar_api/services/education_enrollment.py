from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.education import CourseStatus, EducationCourse
from northstar_api.education_batches import BatchStatus, EducationBatch
from northstar_api.education_enrollments import EducationEnrollment, EnrollmentStatus
from northstar_api.education_students import EducationStudent, StudentStatus

NON_TERMINAL_ENROLLMENT_STATUSES = frozenset(
    {
        EnrollmentStatus.PENDING.value,
        EnrollmentStatus.ACTIVE.value,
        EnrollmentStatus.SUSPENDED.value,
    }
)


async def has_non_terminal_enrollment(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    student_id: UUID | None = None,
    course_id: UUID | None = None,
    batch_id: UUID | None = None,
    agent_id: UUID | None = None,
) -> bool:
    conditions = [
        EducationEnrollment.tenant_id == tenant_id,
        EducationEnrollment.workspace_id == workspace_id,
        EducationEnrollment.status.in_(NON_TERMINAL_ENROLLMENT_STATUSES),
    ]
    if student_id is not None:
        conditions.append(EducationEnrollment.student_id == student_id)
    if course_id is not None:
        conditions.append(EducationEnrollment.course_id == course_id)
    if batch_id is not None:
        conditions.append(EducationEnrollment.batch_id == batch_id)
    if agent_id is not None:
        conditions.append(EducationEnrollment.agent_id == agent_id)
    value = await session.scalar(select(EducationEnrollment.id).where(*conditions).limit(1))
    return value is not None


async def has_active_agent_enrollment_configuration(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    agent_id: UUID,
) -> bool:
    """Return whether an Education Agent has at least one live enrollment assignment.

    This is a provisioning check only. Message-time Education authorization still has to
    resolve identity, enrollment, Course, Batch, Agent, and date scope before RAG.
    """

    value = await session.scalar(
        select(EducationEnrollment.id)
        .join(EducationStudent, EducationStudent.id == EducationEnrollment.student_id)
        .join(EducationCourse, EducationCourse.id == EducationEnrollment.course_id)
        .join(EducationBatch, EducationBatch.id == EducationEnrollment.batch_id)
        .where(
            EducationEnrollment.tenant_id == tenant_id,
            EducationEnrollment.workspace_id == workspace_id,
            EducationEnrollment.agent_id == agent_id,
            EducationEnrollment.status == EnrollmentStatus.ACTIVE.value,
            EducationStudent.status == StudentStatus.ACTIVE.value,
            EducationCourse.status == CourseStatus.ACTIVE.value,
            EducationBatch.status == BatchStatus.ACTIVE.value,
        )
        .limit(1)
    )
    return value is not None
