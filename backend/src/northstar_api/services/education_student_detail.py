from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.education import EducationCourse
from northstar_api.education_batches import EducationBatch
from northstar_api.education_conversation_context import EducationConversationContext
from northstar_api.education_enrollments import EducationEnrollment, EnrollmentStatus
from northstar_api.education_student_activity import EducationStudentActivityEvent
from northstar_api.education_student_detail_schemas import (
    StudentDetailActivityOut,
    StudentDetailConversationOut,
    StudentDetailEnrollmentOut,
    StudentDetailIdentityOut,
    StudentDetailOut,
    StudentDetailSummaryOut,
)
from northstar_api.education_student_identities import (
    EducationStudentIdentity,
    StudentIdentityStatus,
    StudentIdentityType,
)
from northstar_api.education_student_schemas import StudentOut
from northstar_api.education_students import EducationStudent
from northstar_api.models import Agent, Conversation
from northstar_api.services.workspace_dates import workspace_today


class StudentDetailNotFoundError(LookupError):
    pass


def enrollment_access_state(
    status: str,
    starts_on: date | None,
    ends_on: date | None,
    *,
    today: date | None = None,
) -> str:
    current = today or datetime.now(UTC).date()
    if status != EnrollmentStatus.ACTIVE.value:
        return status
    if starts_on is not None and current < starts_on:
        return "scheduled"
    if ends_on is not None and current > ends_on:
        return "expired"
    return "active"


async def get_student_detail(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    student_id: UUID,
    activity_limit: int = 100,
) -> StudentDetailOut:
    student = await session.scalar(
        select(EducationStudent).where(
            EducationStudent.id == student_id,
            EducationStudent.tenant_id == tenant_id,
            EducationStudent.workspace_id == workspace_id,
        )
    )
    if student is None:
        raise StudentDetailNotFoundError("Student not found")
    today = await workspace_today(session, tenant_id=tenant_id, workspace_id=workspace_id)

    identity_rows = (
        await session.scalars(
            select(EducationStudentIdentity)
            .where(
                EducationStudentIdentity.tenant_id == tenant_id,
                EducationStudentIdentity.workspace_id == workspace_id,
                EducationStudentIdentity.student_id == student_id,
            )
            .order_by(
                EducationStudentIdentity.identity_type,
                EducationStudentIdentity.is_primary.desc(),
                EducationStudentIdentity.created_at,
            )
        )
    ).all()
    identities = [
        StudentDetailIdentityOut(
            id=value.id,
            identity_type=StudentIdentityType(value.identity_type),
            identifier=value.identifier,
            label=value.label,
            status=StudentIdentityStatus(value.status),
            is_primary=value.is_primary,
            verified_at=value.verified_at,
            created_at=value.created_at,
        )
        for value in identity_rows
    ]

    enrollment_rows = (
        await session.execute(
            select(EducationEnrollment, EducationCourse, EducationBatch, Agent)
            .join(EducationCourse, EducationCourse.id == EducationEnrollment.course_id)
            .join(EducationBatch, EducationBatch.id == EducationEnrollment.batch_id)
            .join(Agent, Agent.id == EducationEnrollment.agent_id)
            .where(
                EducationEnrollment.tenant_id == tenant_id,
                EducationEnrollment.workspace_id == workspace_id,
                EducationEnrollment.student_id == student_id,
                EducationCourse.tenant_id == tenant_id,
                EducationCourse.workspace_id == workspace_id,
                EducationBatch.tenant_id == tenant_id,
                EducationBatch.workspace_id == workspace_id,
                Agent.tenant_id == tenant_id,
                Agent.workspace_id == workspace_id,
            )
            .order_by(EducationEnrollment.created_at.desc())
        )
    ).all()
    enrollments = [
        StudentDetailEnrollmentOut(
            id=enrollment.id,
            course_id=course.id,
            course_code=course.code,
            course_name=course.name,
            batch_id=batch.id,
            batch_code=batch.code,
            batch_name=batch.name,
            agent_id=agent.id,
            agent_public_id=agent.public_id,
            agent_name=agent.name,
            starts_on=enrollment.starts_on,
            ends_on=enrollment.ends_on,
            status=EnrollmentStatus(enrollment.status),
            access_state=enrollment_access_state(
                enrollment.status,
                enrollment.starts_on,
                enrollment.ends_on,
                today=today,
            ),
            created_at=enrollment.created_at,
            updated_at=enrollment.updated_at,
        )
        for enrollment, course, batch, agent in enrollment_rows
    ]

    conversation_rows = (
        await session.execute(
            select(EducationConversationContext, Conversation, Agent)
            .join(Conversation, Conversation.id == EducationConversationContext.conversation_id)
            .join(Agent, Agent.id == EducationConversationContext.agent_id)
            .where(
                EducationConversationContext.tenant_id == tenant_id,
                EducationConversationContext.workspace_id == workspace_id,
                EducationConversationContext.student_id == student_id,
                Conversation.tenant_id == tenant_id,
                Conversation.workspace_id == workspace_id,
                Agent.tenant_id == tenant_id,
                Agent.workspace_id == workspace_id,
            )
            .order_by(Conversation.updated_at.desc())
        )
    ).all()
    conversations = [
        StudentDetailConversationOut(
            id=conversation.id,
            public_id=conversation.public_id,
            enrollment_id=context.enrollment_id,
            course_id=context.course_id,
            batch_id=context.batch_id,
            agent_id=context.agent_id,
            agent_name=agent.name,
            channel=conversation.channel,
            state=conversation.state,
            resolution=conversation.resolution,
            started_at=conversation.started_at,
            ended_at=conversation.ended_at,
            updated_at=conversation.updated_at,
        )
        for context, conversation, agent in conversation_rows
    ]

    activity_total = int(
        await session.scalar(
            select(func.count(EducationStudentActivityEvent.id)).where(
                EducationStudentActivityEvent.tenant_id == tenant_id,
                EducationStudentActivityEvent.workspace_id == workspace_id,
                EducationStudentActivityEvent.student_id == student_id,
            )
        )
        or 0
    )
    activity_rows = (
        await session.execute(
            select(
                EducationStudentActivityEvent,
                Conversation,
                EducationCourse,
                EducationBatch,
                Agent,
            )
            .join(Conversation, Conversation.id == EducationStudentActivityEvent.conversation_id)
            .join(EducationCourse, EducationCourse.id == EducationStudentActivityEvent.course_id)
            .join(EducationBatch, EducationBatch.id == EducationStudentActivityEvent.batch_id)
            .join(Agent, Agent.id == EducationStudentActivityEvent.agent_id)
            .where(
                EducationStudentActivityEvent.tenant_id == tenant_id,
                EducationStudentActivityEvent.workspace_id == workspace_id,
                EducationStudentActivityEvent.student_id == student_id,
                Conversation.tenant_id == tenant_id,
                Conversation.workspace_id == workspace_id,
                EducationCourse.tenant_id == tenant_id,
                EducationCourse.workspace_id == workspace_id,
                EducationBatch.tenant_id == tenant_id,
                EducationBatch.workspace_id == workspace_id,
                Agent.tenant_id == tenant_id,
                Agent.workspace_id == workspace_id,
            )
            .order_by(EducationStudentActivityEvent.created_at.desc())
            .limit(activity_limit)
        )
    ).all()
    activity = [
        StudentDetailActivityOut(
            id=event.id,
            event_type=event.event_type,
            conversation_id=event.conversation_id,
            conversation_public_id=conversation.public_id,
            enrollment_id=event.enrollment_id,
            course_id=event.course_id,
            course_name=course.name,
            batch_id=event.batch_id,
            batch_name=batch.name,
            agent_id=event.agent_id,
            agent_name=agent.name,
            resolution=event.resolution,
            resolved_at=event.resolved_at,
            actor_user_id=event.actor_user_id,
            details=event.details_json,
            created_at=event.created_at,
        )
        for event, conversation, course, batch, agent in activity_rows
    ]

    timestamps = [conversation.updated_at for conversation in conversations]
    timestamps.extend(item.created_at for item in activity)
    last_active_at = max(timestamps) if timestamps else None
    return StudentDetailOut(
        student=StudentOut.model_validate(student),
        identities=identities,
        enrollments=enrollments,
        conversations=conversations,
        activity=activity,
        summary=StudentDetailSummaryOut(
            verified_identity_count=sum(
                1 for value in identities if value.status == StudentIdentityStatus.VERIFIED
            ),
            active_access_count=sum(1 for value in enrollments if value.access_state == "active"),
            conversation_count=len(conversations),
            activity_count=activity_total,
            last_active_at=last_active_at,
        ),
    )
