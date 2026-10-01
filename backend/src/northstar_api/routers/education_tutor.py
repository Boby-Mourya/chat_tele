from __future__ import annotations

import hmac
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.course_knowledge_models import (
    CourseAcademicReview,
    CourseEnrollmentAccess,
    CoursePaperProgress,
    CoursePracticeAttempt,
    CourseResponseContext,
    CourseStudySelection,
)
from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.education_enrollments import EducationEnrollment
from northstar_api.education_tutor_schemas import (
    AnswerExplanation,
    PracticeCreate,
    PracticeOut,
    PracticeSubmit,
    ProgressOut,
    ReviewAssign,
    ReviewOut,
    ReviewResolve,
    TutorContextOut,
)
from northstar_api.security import Principal

router = APIRouter(prefix="/education", tags=["education"])
DB = Annotated[AsyncSession, Depends(get_session)]
View = Annotated[Principal, Depends(require_permissions("education.view"))]
Manage = Annotated[Principal, Depends(require_permissions("education.manage"))]


def _workspace(principal: Principal) -> UUID:
    if principal.workspace_id is None:
        raise HTTPException(403, "Workspace access is unavailable")
    return principal.workspace_id


def _scope(model: type, principal: Principal) -> tuple:
    return model.tenant_id == principal.tenant_id, model.workspace_id == _workspace(principal)


async def _attempt(session: AsyncSession, principal: Principal, attempt_id: UUID) -> CoursePracticeAttempt:
    row = await session.scalar(
        select(CoursePracticeAttempt).where(
            *_scope(CoursePracticeAttempt, principal), CoursePracticeAttempt.id == attempt_id
        )
    )
    if row is None:
        raise HTTPException(404, "Practice attempt not found")
    return row


async def _validate_practice_scope(
    session: AsyncSession, principal: Principal, payload: PracticeCreate
) -> None:
    enrollment = await session.scalar(
        select(EducationEnrollment).where(
            *_scope(EducationEnrollment, principal),
            EducationEnrollment.id == payload.enrollment_id,
            EducationEnrollment.student_id == payload.student_id,
            EducationEnrollment.agent_id == payload.agent_id,
            EducationEnrollment.status == "active",
        )
    )
    access = await session.scalar(
        select(CourseEnrollmentAccess).where(
            *_scope(CourseEnrollmentAccess, principal),
            CourseEnrollmentAccess.agent_id == payload.agent_id,
            CourseEnrollmentAccess.enrollment_id == payload.enrollment_id,
            CourseEnrollmentAccess.active.is_(True),
        )
    )
    if enrollment is None or access is None or str(payload.paper_id) not in access.paper_ids:
        raise HTTPException(403, "The paper is not authorized for this active enrollment")


async def _progress(session: AsyncSession, attempt: CoursePracticeAttempt) -> CoursePaperProgress:
    row = await session.scalar(
        select(CoursePaperProgress)
        .where(
            CoursePaperProgress.enrollment_id == attempt.enrollment_id,
            CoursePaperProgress.paper_id == attempt.paper_id,
        )
        .with_for_update()
    )
    if row is None:
        row = CoursePaperProgress(
            tenant_id=attempt.tenant_id,
            workspace_id=attempt.workspace_id,
            agent_id=attempt.agent_id,
            student_id=attempt.student_id,
            enrollment_id=attempt.enrollment_id,
            paper_id=attempt.paper_id,
        )
        session.add(row)
        await session.flush()
    return row


@router.post("/practice/attempts", response_model=PracticeOut, status_code=201)
async def create_practice(payload: PracticeCreate, principal: Manage, session: DB) -> PracticeOut:
    await _validate_practice_scope(session, principal, payload)
    existing = await session.scalar(
        select(CoursePracticeAttempt).where(
            *_scope(CoursePracticeAttempt, principal),
            CoursePracticeAttempt.agent_id == payload.agent_id,
            CoursePracticeAttempt.idempotency_key == payload.idempotency_key,
        )
    )
    if existing:
        if (
            existing.enrollment_id != payload.enrollment_id
            or existing.paper_id != payload.paper_id
            or existing.question != payload.question
        ):
            raise HTTPException(409, "The idempotency key belongs to another practice attempt")
        return PracticeOut.model_validate(existing)
    row = CoursePracticeAttempt(
        **payload.model_dump(), tenant_id=principal.tenant_id, workspace_id=_workspace(principal)
    )
    session.add(row)
    progress = await _progress(session, row)
    progress.practice_attempts += 1
    progress.learning_status = "practicing"
    progress.last_activity_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(row)
    return PracticeOut.model_validate(row)


@router.post("/practice/attempts/{attempt_id}/submit", response_model=PracticeOut)
async def submit_practice(
    attempt_id: UUID, payload: PracticeSubmit, principal: Manage, session: DB
) -> PracticeOut:
    row = await _attempt(session, principal, attempt_id)
    if row.status == "answered":
        if row.student_answer != payload.student_answer:
            raise HTTPException(409, "This attempt was already answered")
        return PracticeOut.model_validate(row)
    row.student_answer = payload.student_answer.strip()
    row.is_correct = hmac.compare_digest(row.student_answer.casefold(), row.answer_key.strip().casefold())
    row.feedback = (
        "Correct." if row.is_correct else "Not correct. Review the approved lesson and try a new question."
    )
    row.status = "answered"
    progress = await _progress(session, row)
    progress.objective_answers_graded += 1
    progress.objective_answers_correct += int(row.is_correct)
    progress.learning_status = "practicing" if row.is_correct else "review_needed"
    progress.last_activity_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(row)
    return PracticeOut.model_validate(row)


@router.get("/progress", response_model=list[ProgressOut])
async def list_progress(
    principal: View,
    session: DB,
    agent_id: UUID | None = None,
    student_id: UUID | None = None,
    enrollment_id: UUID | None = None,
    paper_id: UUID | None = None,
) -> list[ProgressOut]:
    conditions = [*_scope(CoursePaperProgress, principal)]
    for column, value in (
        (CoursePaperProgress.agent_id, agent_id),
        (CoursePaperProgress.student_id, student_id),
        (CoursePaperProgress.enrollment_id, enrollment_id),
        (CoursePaperProgress.paper_id, paper_id),
    ):
        if value is not None:
            conditions.append(column == value)
    rows = (
        await session.scalars(
            select(CoursePaperProgress)
            .where(*conditions)
            .order_by(CoursePaperProgress.last_activity_at.desc())
        )
    ).all()
    return [ProgressOut.model_validate(row) for row in rows]


@router.get("/academic-reviews", response_model=list[ReviewOut])
async def list_reviews(
    principal: View,
    session: DB,
    status: str | None = Query(default=None),
    agent_id: UUID | None = None,
    course_id: UUID | None = None,
) -> list[ReviewOut]:
    conditions = [*_scope(CourseAcademicReview, principal)]
    if agent_id:
        conditions.append(CourseAcademicReview.agent_id == agent_id)
    if status:
        conditions.append(CourseAcademicReview.status == status)
    if course_id:
        conditions.append(CourseAcademicReview.course_id == course_id)
    rows = (
        await session.scalars(
            select(CourseAcademicReview).where(*conditions).order_by(CourseAcademicReview.created_at.desc())
        )
    ).all()
    return [ReviewOut.model_validate(row) for row in rows]


@router.post("/academic-reviews/{review_id}/assign", response_model=ReviewOut)
async def assign_review(review_id: UUID, payload: ReviewAssign, principal: Manage, session: DB) -> ReviewOut:
    row = await session.scalar(
        select(CourseAcademicReview)
        .where(*_scope(CourseAcademicReview, principal), CourseAcademicReview.id == review_id)
        .with_for_update()
    )
    if row is None:
        raise HTTPException(404, "Academic review not found")
    if row.status in {"corrected", "confirmed", "closed"}:
        raise HTTPException(409, "Closed reviews cannot be reassigned")
    row.assigned_reviewer = payload.reviewer_id
    row.status = "assigned"
    await session.commit()
    await session.refresh(row)
    return ReviewOut.model_validate(row)


@router.post("/academic-reviews/{review_id}/resolve", response_model=ReviewOut)
async def resolve_review(
    review_id: UUID, payload: ReviewResolve, principal: Manage, session: DB
) -> ReviewOut:
    row = await session.scalar(
        select(CourseAcademicReview)
        .where(*_scope(CourseAcademicReview, principal), CourseAcademicReview.id == review_id)
        .with_for_update()
    )
    if row is None:
        raise HTTPException(404, "Academic review not found")
    row.resolution = payload.resolution
    row.status = payload.outcome
    row.reviewed_at = datetime.now(UTC)
    row.correction_delivery_status = "requested" if payload.request_correction_delivery else "not_requested"
    await session.commit()
    await session.refresh(row)
    return ReviewOut.model_validate(row)


@router.get("/tutor-contexts", response_model=list[TutorContextOut])
async def list_tutor_contexts(
    principal: View, session: DB, agent_id: UUID | None = None, identity_id: UUID | None = None
) -> list[TutorContextOut]:
    conditions = [*_scope(CourseStudySelection, principal)]
    if agent_id:
        conditions.append(CourseStudySelection.agent_id == agent_id)
    if identity_id:
        conditions.append(CourseStudySelection.identity_id == identity_id)
    rows = (
        await session.scalars(
            select(CourseStudySelection).where(*conditions).order_by(CourseStudySelection.created_at.desc())
        )
    ).all()
    return [
        TutorContextOut(
            identity_id=row.identity_id,
            agent_id=row.agent_id,
            enrollment_id=row.enrollment_id,
            interaction_state=row.interaction_state,
            menu_id=row.menu_id,
            menu_options=row.menu_ids,
            menu_created_at=row.menu_created_at,
            menu_expires_at=row.menu_expires_at,
            selection_revision=row.selection_revision,
            pending_question=row.pending_question,
        )
        for row in rows
    ]


@router.delete("/tutor-contexts/{identity_id}/{agent_id}", status_code=204)
async def reset_tutor_context(identity_id: UUID, agent_id: UUID, principal: Manage, session: DB) -> Response:
    row = await session.scalar(
        select(CourseStudySelection)
        .where(
            *_scope(CourseStudySelection, principal),
            CourseStudySelection.identity_id == identity_id,
            CourseStudySelection.agent_id == agent_id,
        )
        .with_for_update()
    )
    if row:
        await session.delete(row)
        await session.commit()
    return Response(status_code=204)


@router.get("/answers/{message_id}/explanation", response_model=AnswerExplanation)
async def explain_answer(message_id: UUID, principal: View, session: DB) -> AnswerExplanation:
    context = await session.scalar(
        select(CourseResponseContext).where(
            *_scope(CourseResponseContext, principal), CourseResponseContext.message_id == message_id
        )
    )
    if context is None:
        raise HTTPException(404, "Education answer context not found")
    review = await session.scalar(
        select(CourseAcademicReview).where(
            *_scope(CourseAcademicReview, principal), CourseAcademicReview.message_id == message_id
        )
    )
    return AnswerExplanation(
        message_id=message_id,
        enrollment_id=context.enrollment_id,
        context_fingerprint=context.context_fingerprint,
        retrieved_sources=context.citations,
        fallback_reason=review.reason if review else None,
        academic_review_id=review.id if review else None,
        academic_review_status=review.status if review else None,
    )
