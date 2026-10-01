from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.agent_purpose import AgentPurpose, get_agent_purpose
from northstar_api.education import CourseStatus, EducationCourse
from northstar_api.education_batches import BatchStatus, EducationBatch
from northstar_api.education_conversation_context import EducationConversationContext
from northstar_api.education_curricula import CurriculumStatus, EducationCurriculum
from northstar_api.education_enrollments import EducationEnrollment, EnrollmentStatus
from northstar_api.education_papers import EducationPaper, PaperStatus
from northstar_api.education_students import EducationStudent, StudentStatus
from northstar_api.models import Agent, AgentStatus
from northstar_api.modules.knowledge.retrieval import EducationRetrievalScope
from northstar_api.services.workspace_dates import workspace_today


class EducationRagAccessDenied(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def authorized_education_retrieval_scope(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    agent: Agent,
    conversation_id: UUID,
) -> EducationRetrievalScope:
    """Revalidate the durable Education conversation scope before every RAG retrieval."""

    if (
        agent.tenant_id != tenant_id
        or agent.workspace_id != workspace_id
        or agent.deleted_at is not None
        or agent.status is not AgentStatus.ACTIVE
    ):
        raise EducationRagAccessDenied("agent_inactive")

    purpose = await get_agent_purpose(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        agent_id=agent.id,
    )
    if purpose is not AgentPurpose.EDUCATION:
        raise EducationRagAccessDenied("agent_not_education")

    context = await session.scalar(
        select(EducationConversationContext).where(
            EducationConversationContext.tenant_id == tenant_id,
            EducationConversationContext.workspace_id == workspace_id,
            EducationConversationContext.agent_id == agent.id,
            EducationConversationContext.conversation_id == conversation_id,
        )
    )
    if context is None:
        raise EducationRagAccessDenied("education_context_missing")

    enrollment = await session.scalar(
        select(EducationEnrollment).where(
            EducationEnrollment.id == context.enrollment_id,
            EducationEnrollment.tenant_id == tenant_id,
            EducationEnrollment.workspace_id == workspace_id,
            EducationEnrollment.agent_id == agent.id,
            EducationEnrollment.student_id == context.student_id,
            EducationEnrollment.course_id == context.course_id,
            EducationEnrollment.batch_id == context.batch_id,
            EducationEnrollment.status == EnrollmentStatus.ACTIVE.value,
        )
    )
    if enrollment is None:
        raise EducationRagAccessDenied("enrollment_inactive")

    student = await session.scalar(
        select(EducationStudent).where(
            EducationStudent.id == context.student_id,
            EducationStudent.tenant_id == tenant_id,
            EducationStudent.workspace_id == workspace_id,
            EducationStudent.status == StudentStatus.ACTIVE.value,
        )
    )
    if student is None:
        raise EducationRagAccessDenied("student_inactive")

    course = await session.scalar(
        select(EducationCourse).where(
            EducationCourse.id == context.course_id,
            EducationCourse.tenant_id == tenant_id,
            EducationCourse.workspace_id == workspace_id,
            EducationCourse.status == CourseStatus.ACTIVE.value,
        )
    )
    if course is None:
        raise EducationRagAccessDenied("course_inactive")

    batch = await session.scalar(
        select(EducationBatch).where(
            EducationBatch.id == context.batch_id,
            EducationBatch.tenant_id == tenant_id,
            EducationBatch.workspace_id == workspace_id,
            EducationBatch.course_id == context.course_id,
            EducationBatch.status == BatchStatus.ACTIVE.value,
        )
    )
    if batch is None:
        raise EducationRagAccessDenied("batch_inactive")

    curriculum_id = context.curriculum_id or batch.curriculum_id
    if enrollment.curriculum_id is not None and curriculum_id != enrollment.curriculum_id:
        raise EducationRagAccessDenied("curriculum_not_authorized")
    if curriculum_id is not None:
        curriculum = await session.scalar(
            select(EducationCurriculum).where(
                EducationCurriculum.id == curriculum_id,
                EducationCurriculum.tenant_id == tenant_id,
                EducationCurriculum.workspace_id == workspace_id,
                EducationCurriculum.course_id == context.course_id,
                EducationCurriculum.status == CurriculumStatus.ACTIVE.value,
            )
        )
        if curriculum is None:
            raise EducationRagAccessDenied("curriculum_inactive")
    if context.paper_id is not None:
        paper = await session.scalar(
            select(EducationPaper).where(
                EducationPaper.id == context.paper_id,
                EducationPaper.tenant_id == tenant_id,
                EducationPaper.workspace_id == workspace_id,
                EducationPaper.course_id == context.course_id,
                EducationPaper.curriculum_id == curriculum_id,
                EducationPaper.status == PaperStatus.ACTIVE.value,
            )
        )
        if paper is None:
            raise EducationRagAccessDenied("paper_inactive")
        if not enrollment.all_papers and str(context.paper_id) not in enrollment.paper_ids:
            raise EducationRagAccessDenied("paper_not_authorized")

    today = await workspace_today(session, tenant_id=tenant_id, workspace_id=workspace_id)
    if batch.starts_on is not None and today < batch.starts_on:
        raise EducationRagAccessDenied("batch_not_started")
    if batch.ends_on is not None and today > batch.ends_on:
        raise EducationRagAccessDenied("batch_ended")
    if enrollment.starts_on is not None and today < enrollment.starts_on:
        raise EducationRagAccessDenied("access_not_started")
    if enrollment.ends_on is not None and today > enrollment.ends_on:
        raise EducationRagAccessDenied("access_ended")

    return EducationRetrievalScope(
        workspace_id=workspace_id,
        student_id=context.student_id,
        enrollment_id=context.enrollment_id,
        course_id=context.course_id,
        batch_id=context.batch_id,
        curriculum_id=curriculum_id,
        paper_id=context.paper_id,
    )
