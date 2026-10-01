from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.agent_purpose import AgentPurpose, get_agent_purpose
from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.education import CourseStatus, EducationCourse
from northstar_api.education_batches import BatchStatus, EducationBatch
from northstar_api.education_enrollment_schemas import EnrollmentCreate, EnrollmentOut, EnrollmentPatch
from northstar_api.education_enrollments import EducationEnrollment, EnrollmentStatus
from northstar_api.education_papers import EducationPaper, PaperStatus
from northstar_api.education_students import EducationStudent, StudentStatus
from northstar_api.models import Agent
from northstar_api.security import Principal
from northstar_api.services.outbox import enqueue_event

router = APIRouter(prefix="/education/enrollments", tags=["education"])
DB = Annotated[AsyncSession, Depends(get_session)]
EducationViewPrincipal = Annotated[Principal, Depends(require_permissions("education.view"))]
EducationManagePrincipal = Annotated[Principal, Depends(require_permissions("education.manage"))]

_NON_TERMINAL = {
    EnrollmentStatus.PENDING,
    EnrollmentStatus.ACTIVE,
    EnrollmentStatus.SUSPENDED,
}
_ALLOWED_TRANSITIONS: dict[EnrollmentStatus, frozenset[EnrollmentStatus]] = {
    EnrollmentStatus.PENDING: frozenset(
        {
            EnrollmentStatus.PENDING,
            EnrollmentStatus.ACTIVE,
            EnrollmentStatus.SUSPENDED,
            EnrollmentStatus.EXPIRED,
            EnrollmentStatus.REVOKED,
        }
    ),
    EnrollmentStatus.ACTIVE: frozenset(
        {
            EnrollmentStatus.ACTIVE,
            EnrollmentStatus.SUSPENDED,
            EnrollmentStatus.EXPIRED,
            EnrollmentStatus.REVOKED,
            EnrollmentStatus.GRADUATED,
        }
    ),
    EnrollmentStatus.SUSPENDED: frozenset(
        {
            EnrollmentStatus.SUSPENDED,
            EnrollmentStatus.ACTIVE,
            EnrollmentStatus.EXPIRED,
            EnrollmentStatus.REVOKED,
            EnrollmentStatus.GRADUATED,
        }
    ),
    EnrollmentStatus.EXPIRED: frozenset(
        {
            EnrollmentStatus.EXPIRED,
            EnrollmentStatus.ACTIVE,
            EnrollmentStatus.REVOKED,
            EnrollmentStatus.GRADUATED,
        }
    ),
    EnrollmentStatus.REVOKED: frozenset(
        {
            EnrollmentStatus.REVOKED,
            EnrollmentStatus.PENDING,
        }
    ),
    EnrollmentStatus.GRADUATED: frozenset({EnrollmentStatus.GRADUATED}),
}


def _workspace_id(principal: Principal) -> UUID:
    if principal.workspace_id is None:
        raise HTTPException(status_code=403, detail="Workspace access is unavailable")
    return principal.workspace_id


def _enrollment_out(enrollment: EducationEnrollment) -> EnrollmentOut:
    return EnrollmentOut.model_validate(enrollment)


def _validate_date_range(starts_on: date | None, ends_on: date | None) -> None:
    if starts_on and ends_on and ends_on < starts_on:
        raise HTTPException(status_code=422, detail="Enrollment end date cannot be before start date")


def _validate_transition(current: EnrollmentStatus, next_status: EnrollmentStatus) -> None:
    if next_status not in _ALLOWED_TRANSITIONS[current]:
        raise HTTPException(
            status_code=409,
            detail=f"Enrollment cannot move from {current.value} to {next_status.value}",
        )


async def _scoped_enrollment(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    enrollment_id: UUID,
) -> EducationEnrollment:
    enrollment = await session.scalar(
        select(EducationEnrollment).where(
            EducationEnrollment.id == enrollment_id,
            EducationEnrollment.tenant_id == tenant_id,
            EducationEnrollment.workspace_id == workspace_id,
        )
    )
    if enrollment is None:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    return enrollment


async def _require_active_student_for_enrollment_mutation(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    enrollment: EducationEnrollment,
) -> None:
    student_status = await session.scalar(
        select(EducationStudent.status).where(
            EducationStudent.id == enrollment.student_id,
            EducationStudent.tenant_id == tenant_id,
            EducationStudent.workspace_id == workspace_id,
        )
    )
    if student_status != StudentStatus.ACTIVE.value:
        raise HTTPException(
            status_code=409,
            detail="Reactivate the Student before changing enrollment access",
        )


async def _validate_assignment(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    student_id: UUID,
    course_id: UUID,
    batch_id: UUID,
    agent_id: UUID,
    require_active_domain: bool,
) -> tuple[EducationStudent, EducationCourse, EducationBatch, Agent]:
    student = await session.scalar(
        select(EducationStudent).where(
            EducationStudent.id == student_id,
            EducationStudent.tenant_id == tenant_id,
            EducationStudent.workspace_id == workspace_id,
        )
    )
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")

    course = await session.scalar(
        select(EducationCourse).where(
            EducationCourse.id == course_id,
            EducationCourse.tenant_id == tenant_id,
            EducationCourse.workspace_id == workspace_id,
        )
    )
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found")

    batch = await session.scalar(
        select(EducationBatch).where(
            EducationBatch.id == batch_id,
            EducationBatch.tenant_id == tenant_id,
            EducationBatch.workspace_id == workspace_id,
        )
    )
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found")
    if batch.course_id != course.id:
        raise HTTPException(status_code=422, detail="Batch does not belong to the selected Course")

    agent = await session.scalar(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.tenant_id == tenant_id,
            Agent.workspace_id == workspace_id,
            Agent.deleted_at.is_(None),
        )
    )
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    purpose = await get_agent_purpose(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        agent_id=agent.id,
    )
    if purpose is not AgentPurpose.EDUCATION:
        raise HTTPException(status_code=422, detail="Enrollment Agent must have Education purpose")

    if require_active_domain:
        if student.status != StudentStatus.ACTIVE.value:
            raise HTTPException(
                status_code=409, detail="Reactivate the Student before assigning enrollment access"
            )
        if course.status != CourseStatus.ACTIVE.value:
            raise HTTPException(
                status_code=409, detail="Reactivate the Course before assigning enrollment access"
            )
        if batch.status != BatchStatus.ACTIVE.value:
            raise HTTPException(
                status_code=409, detail="Reactivate the Batch before assigning enrollment access"
            )

    return student, course, batch, agent


async def _validate_paper_access(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    course_id: UUID,
    batch: EducationBatch,
    curriculum_id: UUID | None,
    all_papers: bool,
    paper_ids: list[UUID],
) -> UUID:
    selected_curriculum_id = curriculum_id or batch.curriculum_id
    if selected_curriculum_id is None or batch.curriculum_id != selected_curriculum_id:
        raise HTTPException(status_code=422, detail="Enrollment Curriculum must match the selected Batch")
    if all_papers and paper_ids:
        raise HTTPException(status_code=422, detail="Choose all Papers or explicit Paper grants, not both")
    if not all_papers and not paper_ids:
        raise HTTPException(status_code=422, detail="Explicit Paper access requires at least one Paper")
    if len(set(paper_ids)) != len(paper_ids):
        raise HTTPException(status_code=422, detail="Enrollment Paper grants must be unique")
    if paper_ids:
        valid_ids = set(
            await session.scalars(
                select(EducationPaper.id).where(
                    EducationPaper.id.in_(paper_ids),
                    EducationPaper.tenant_id == tenant_id,
                    EducationPaper.workspace_id == workspace_id,
                    EducationPaper.course_id == course_id,
                    EducationPaper.curriculum_id == selected_curriculum_id,
                    EducationPaper.status == PaperStatus.ACTIVE.value,
                )
            )
        )
        if valid_ids != set(paper_ids):
            raise HTTPException(status_code=422, detail="Every granted Paper must belong to the Enrollment Curriculum")
    return selected_curriculum_id


@router.get("", response_model=list[EnrollmentOut])
async def list_enrollments(
    principal: EducationViewPrincipal,
    session: DB,
    enrollment_status: EnrollmentStatus | None = Query(default=None, alias="status"),
    student_id: UUID | None = Query(default=None),
    course_id: UUID | None = Query(default=None),
    batch_id: UUID | None = Query(default=None),
    agent_id: UUID | None = Query(default=None),
) -> list[EnrollmentOut]:
    workspace_id = _workspace_id(principal)
    conditions = [
        EducationEnrollment.tenant_id == principal.tenant_id,
        EducationEnrollment.workspace_id == workspace_id,
    ]
    if enrollment_status is not None:
        conditions.append(EducationEnrollment.status == enrollment_status.value)
    if student_id is not None:
        conditions.append(EducationEnrollment.student_id == student_id)
    if course_id is not None:
        conditions.append(EducationEnrollment.course_id == course_id)
    if batch_id is not None:
        conditions.append(EducationEnrollment.batch_id == batch_id)
    if agent_id is not None:
        conditions.append(EducationEnrollment.agent_id == agent_id)
    enrollments = (
        await session.scalars(
            select(EducationEnrollment)
            .where(*conditions)
            .order_by(EducationEnrollment.updated_at.desc(), EducationEnrollment.created_at.desc())
        )
    ).all()
    return [_enrollment_out(enrollment) for enrollment in enrollments]


@router.post("", response_model=EnrollmentOut, status_code=201)
async def create_enrollment(
    payload: EnrollmentCreate,
    principal: EducationManagePrincipal,
    session: DB,
) -> EnrollmentOut:
    workspace_id = _workspace_id(principal)
    _, _, batch, _ = await _validate_assignment(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        student_id=payload.student_id,
        course_id=payload.course_id,
        batch_id=payload.batch_id,
        agent_id=payload.agent_id,
        require_active_domain=True,
    )
    curriculum_id = await _validate_paper_access(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        course_id=payload.course_id,
        batch=batch,
        curriculum_id=payload.curriculum_id,
        all_papers=payload.all_papers,
        paper_ids=payload.paper_ids,
    )
    _validate_date_range(payload.starts_on, payload.ends_on)
    enrollment = EducationEnrollment(
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        student_id=payload.student_id,
        course_id=payload.course_id,
        curriculum_id=curriculum_id,
        batch_id=payload.batch_id,
        agent_id=payload.agent_id,
        all_papers=payload.all_papers,
        paper_ids=[str(item) for item in payload.paper_ids],
        starts_on=payload.starts_on,
        ends_on=payload.ends_on,
        status=payload.status.value,
    )
    session.add(enrollment)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="This Student already has an Enrollment for the selected Course, Batch, and Agent",
        ) from None
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="education_enrollment",
        aggregate_id=enrollment.id,
        event_type="education.enrollment.created.v1",
        payload={
            "enrollmentId": str(enrollment.id),
            "workspaceId": str(workspace_id),
            "studentId": str(enrollment.student_id),
            "courseId": str(enrollment.course_id),
            "batchId": str(enrollment.batch_id),
            "agentId": str(enrollment.agent_id),
            "status": enrollment.status,
        },
    )
    await session.commit()
    await session.refresh(enrollment)
    return _enrollment_out(enrollment)


@router.get("/{enrollment_id}", response_model=EnrollmentOut)
async def get_enrollment(
    enrollment_id: UUID,
    principal: EducationViewPrincipal,
    session: DB,
) -> EnrollmentOut:
    return _enrollment_out(
        await _scoped_enrollment(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=_workspace_id(principal),
            enrollment_id=enrollment_id,
        )
    )


@router.patch("/{enrollment_id}", response_model=EnrollmentOut)
async def update_enrollment(
    enrollment_id: UUID,
    payload: EnrollmentPatch,
    principal: EducationManagePrincipal,
    session: DB,
) -> EnrollmentOut:
    workspace_id = _workspace_id(principal)
    enrollment = await _scoped_enrollment(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        enrollment_id=enrollment_id,
    )
    await _require_active_student_for_enrollment_mutation(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        enrollment=enrollment,
    )
    current_status = EnrollmentStatus(enrollment.status)
    next_status = payload.status or current_status
    _validate_transition(current_status, next_status)

    assignment_fields = {"course_id", "curriculum_id", "batch_id", "agent_id"}
    assignment_changed = any(
        field_name in payload.model_fields_set
        and getattr(payload, field_name) is not None
        and getattr(enrollment, field_name) != getattr(payload, field_name)
        for field_name in assignment_fields
    )
    if assignment_changed and current_status not in {EnrollmentStatus.PENDING, EnrollmentStatus.SUSPENDED}:
        raise HTTPException(
            status_code=409,
            detail="Suspend the Enrollment before changing Course, Batch, or Agent assignment",
        )

    next_course_id = payload.course_id or enrollment.course_id
    next_batch_id = payload.batch_id or enrollment.batch_id
    next_agent_id = payload.agent_id or enrollment.agent_id
    next_curriculum_id = (
        payload.curriculum_id
        if payload.curriculum_id is not None
        else None
        if assignment_changed
        else enrollment.curriculum_id
    )
    next_all_papers = payload.all_papers if payload.all_papers is not None else enrollment.all_papers
    next_paper_ids = (
        payload.paper_ids
        if payload.paper_ids is not None
        else [UUID(value) for value in enrollment.paper_ids]
    )
    next_starts_on = payload.starts_on if "starts_on" in payload.model_fields_set else enrollment.starts_on
    next_ends_on = payload.ends_on if "ends_on" in payload.model_fields_set else enrollment.ends_on
    _validate_date_range(next_starts_on, next_ends_on)

    if next_status in _NON_TERMINAL or assignment_changed:
        _, _, next_batch, _ = await _validate_assignment(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=workspace_id,
            student_id=enrollment.student_id,
            course_id=next_course_id,
            batch_id=next_batch_id,
            agent_id=next_agent_id,
            require_active_domain=next_status in _NON_TERMINAL,
        )
        next_curriculum_id = await _validate_paper_access(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=workspace_id,
            course_id=next_course_id,
            batch=next_batch,
            curriculum_id=next_curriculum_id,
            all_papers=next_all_papers,
            paper_ids=next_paper_ids,
        )

    changed_fields: list[str] = []
    for field_name in payload.model_fields_set:
        value = getattr(payload, field_name)
        if field_name in assignment_fields and value is None:
            continue
        if field_name == "status":
            if value is None:
                continue
            value = value.value
        elif field_name == "paper_ids":
            value = [str(item) for item in (value or [])]
        if getattr(enrollment, field_name) == value:
            continue
        setattr(enrollment, field_name, value)
        changed_fields.append(field_name)

    if enrollment.curriculum_id != next_curriculum_id:
        enrollment.curriculum_id = next_curriculum_id
        if "curriculum_id" not in changed_fields:
            changed_fields.append("curriculum_id")

    if not changed_fields:
        return _enrollment_out(enrollment)

    enrollment.authorization_revision += 1

    status_changed = enrollment.status != current_status.value
    event_type = (
        "education.enrollment.status_changed.v1" if status_changed else "education.enrollment.updated.v1"
    )
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="education_enrollment",
        aggregate_id=enrollment.id,
        event_type=event_type,
        payload={
            "enrollmentId": str(enrollment.id),
            "workspaceId": str(workspace_id),
            "studentId": str(enrollment.student_id),
            "courseId": str(enrollment.course_id),
            "batchId": str(enrollment.batch_id),
            "agentId": str(enrollment.agent_id),
            "previousStatus": current_status.value,
            "status": enrollment.status,
            "fields": sorted(changed_fields),
        },
    )
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="This Student already has an Enrollment for the selected Course, Batch, and Agent",
        ) from None
    await session.refresh(enrollment)
    return _enrollment_out(enrollment)


@router.delete("/{enrollment_id}", status_code=204)
async def revoke_enrollment(
    enrollment_id: UUID,
    principal: EducationManagePrincipal,
    session: DB,
) -> Response:
    workspace_id = _workspace_id(principal)
    enrollment = await _scoped_enrollment(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        enrollment_id=enrollment_id,
    )
    await _require_active_student_for_enrollment_mutation(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        enrollment=enrollment,
    )
    current_status = EnrollmentStatus(enrollment.status)
    if current_status is EnrollmentStatus.GRADUATED:
        raise HTTPException(status_code=409, detail="Graduated Enrollment history cannot be revoked")
    if current_status is not EnrollmentStatus.REVOKED:
        enrollment.status = EnrollmentStatus.REVOKED.value
        enqueue_event(
            session,
            tenant_id=principal.tenant_id,
            aggregate_type="education_enrollment",
            aggregate_id=enrollment.id,
            event_type="education.enrollment.revoked.v1",
            payload={
                "enrollmentId": str(enrollment.id),
                "workspaceId": str(workspace_id),
                "studentId": str(enrollment.student_id),
                "courseId": str(enrollment.course_id),
                "batchId": str(enrollment.batch_id),
                "agentId": str(enrollment.agent_id),
                "previousStatus": current_status.value,
            },
        )
        await session.commit()
    return Response(status_code=204)
