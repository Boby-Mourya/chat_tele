from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.education import CourseStatus, EducationCourse
from northstar_api.education_batch_schemas import BatchCreate, BatchOut, BatchPatch
from northstar_api.education_batches import BatchStatus, EducationBatch
from northstar_api.education_curricula import CurriculumStatus, EducationCurriculum
from northstar_api.security import Principal
from northstar_api.services.education_catalog import ensure_default_curriculum
from northstar_api.services.education_enrollment import has_non_terminal_enrollment
from northstar_api.services.outbox import enqueue_event

router = APIRouter(prefix="/education/batches", tags=["education"])
DB = Annotated[AsyncSession, Depends(get_session)]
EducationViewPrincipal = Annotated[Principal, Depends(require_permissions("education.view"))]
EducationManagePrincipal = Annotated[Principal, Depends(require_permissions("education.manage"))]


def _workspace_id(principal: Principal) -> UUID:
    if principal.workspace_id is None:
        raise HTTPException(status_code=403, detail="Workspace access is unavailable")
    return principal.workspace_id


async def _scoped_course(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    course_id: UUID,
    require_active: bool = False,
) -> EducationCourse:
    course = await session.scalar(
        select(EducationCourse).where(
            EducationCourse.id == course_id,
            EducationCourse.tenant_id == tenant_id,
            EducationCourse.workspace_id == workspace_id,
        )
    )
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found")
    if require_active and course.status != CourseStatus.ACTIVE.value:
        raise HTTPException(status_code=409, detail="Archived courses cannot receive active batches")
    return course


async def _scoped_batch(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    batch_id: UUID,
) -> EducationBatch:
    batch = await session.scalar(
        select(EducationBatch).where(
            EducationBatch.id == batch_id,
            EducationBatch.tenant_id == tenant_id,
            EducationBatch.workspace_id == workspace_id,
        )
    )
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found")
    return batch


async def _resolve_curriculum(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    course_id: UUID,
    curriculum_id: UUID | None,
) -> EducationCurriculum:
    if curriculum_id is None:
        return await ensure_default_curriculum(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            course_id=course_id,
        )
    curriculum = await session.scalar(
        select(EducationCurriculum).where(
            EducationCurriculum.id == curriculum_id,
            EducationCurriculum.tenant_id == tenant_id,
            EducationCurriculum.workspace_id == workspace_id,
            EducationCurriculum.course_id == course_id,
            EducationCurriculum.status == CurriculumStatus.ACTIVE.value,
        )
    )
    if curriculum is None:
        raise HTTPException(
            status_code=422,
            detail="Curriculum must be active and belong to the selected Course",
        )
    return curriculum


async def _ensure_batch_has_no_live_enrollments(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    batch_id: UUID,
) -> None:
    if await has_non_terminal_enrollment(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        batch_id=batch_id,
    ):
        raise HTTPException(
            status_code=409,
            detail="Resolve non-terminal Enrollments before archiving this Batch",
        )


def _batch_out(batch: EducationBatch) -> BatchOut:
    return BatchOut.model_validate(batch)


def _validate_date_range(starts_on: date | None, ends_on: date | None) -> None:
    if starts_on and ends_on and ends_on < starts_on:
        raise HTTPException(status_code=422, detail="Batch end date cannot be before start date")


@router.get("", response_model=list[BatchOut])
async def list_batches(
    principal: EducationViewPrincipal,
    session: DB,
    batch_status: BatchStatus | None = Query(default=None, alias="status"),
    course_id: UUID | None = Query(default=None),
    search: str | None = Query(default=None, max_length=120),
) -> list[BatchOut]:
    workspace_id = _workspace_id(principal)
    conditions = [
        EducationBatch.tenant_id == principal.tenant_id,
        EducationBatch.workspace_id == workspace_id,
    ]
    if batch_status is not None:
        conditions.append(EducationBatch.status == batch_status.value)
    if course_id is not None:
        conditions.append(EducationBatch.course_id == course_id)
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        conditions.append(
            or_(
                EducationBatch.code.ilike(pattern),
                EducationBatch.name.ilike(pattern),
                EducationBatch.description.ilike(pattern),
            )
        )
    batches = (
        await session.scalars(
            select(EducationBatch)
            .where(*conditions)
            .order_by(EducationBatch.status, EducationBatch.name, EducationBatch.code)
        )
    ).all()
    return [_batch_out(batch) for batch in batches]


@router.post("", response_model=BatchOut, status_code=201)
async def create_batch(
    payload: BatchCreate,
    principal: EducationManagePrincipal,
    session: DB,
) -> BatchOut:
    workspace_id = _workspace_id(principal)
    await _scoped_course(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        course_id=payload.course_id,
        require_active=True,
    )
    curriculum = await _resolve_curriculum(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        course_id=payload.course_id,
        curriculum_id=payload.curriculum_id,
    )
    batch = EducationBatch(
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        course_id=payload.course_id,
        curriculum_id=curriculum.id,
        code=payload.code,
        name=payload.name,
        description=payload.description,
        starts_on=payload.starts_on,
        ends_on=payload.ends_on,
        status=BatchStatus.ACTIVE.value,
    )
    session.add(batch)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="A batch with this code already exists in this workspace",
        ) from None
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="education_batch",
        aggregate_id=batch.id,
        event_type="education.batch.created.v1",
        payload={
            "batchId": str(batch.id),
            "workspaceId": str(workspace_id),
            "courseId": str(batch.course_id),
            "curriculumId": str(batch.curriculum_id),
            "code": batch.code,
            "name": batch.name,
        },
    )
    await session.commit()
    await session.refresh(batch)
    return _batch_out(batch)


@router.get("/{batch_id}", response_model=BatchOut)
async def get_batch(
    batch_id: UUID,
    principal: EducationViewPrincipal,
    session: DB,
) -> BatchOut:
    return _batch_out(
        await _scoped_batch(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=_workspace_id(principal),
            batch_id=batch_id,
        )
    )


@router.patch("/{batch_id}", response_model=BatchOut)
async def update_batch(
    batch_id: UUID,
    payload: BatchPatch,
    principal: EducationManagePrincipal,
    session: DB,
) -> BatchOut:
    workspace_id = _workspace_id(principal)
    batch = await _scoped_batch(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        batch_id=batch_id,
    )
    next_starts_on = payload.starts_on if "starts_on" in payload.model_fields_set else batch.starts_on
    next_ends_on = payload.ends_on if "ends_on" in payload.model_fields_set else batch.ends_on
    _validate_date_range(next_starts_on, next_ends_on)

    if payload.status == BatchStatus.ACTIVE and batch.status != BatchStatus.ACTIVE.value:
        await _scoped_course(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=workspace_id,
            course_id=batch.course_id,
            require_active=True,
        )
    if payload.status == BatchStatus.ARCHIVED and batch.status != BatchStatus.ARCHIVED.value:
        await _ensure_batch_has_no_live_enrollments(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=workspace_id,
            batch_id=batch.id,
        )

    changed_fields: list[str] = []
    for field_name in payload.model_fields_set:
        value = getattr(payload, field_name)
        if field_name == "status" and value is not None:
            value = value.value
        if getattr(batch, field_name) == value:
            continue
        setattr(batch, field_name, value)
        changed_fields.append(field_name)

    if not changed_fields:
        return _batch_out(batch)

    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="education_batch",
        aggregate_id=batch.id,
        event_type="education.batch.updated.v1",
        payload={
            "batchId": str(batch.id),
            "workspaceId": str(batch.workspace_id),
            "courseId": str(batch.course_id),
            "fields": sorted(changed_fields),
            "status": batch.status,
        },
    )
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="A batch with this code already exists in this workspace",
        ) from None
    await session.refresh(batch)
    return _batch_out(batch)


@router.delete("/{batch_id}", status_code=204)
async def archive_batch(
    batch_id: UUID,
    principal: EducationManagePrincipal,
    session: DB,
) -> Response:
    batch = await _scoped_batch(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=_workspace_id(principal),
        batch_id=batch_id,
    )
    if batch.status != BatchStatus.ARCHIVED.value:
        await _ensure_batch_has_no_live_enrollments(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=batch.workspace_id,
            batch_id=batch.id,
        )
        batch.status = BatchStatus.ARCHIVED.value
        enqueue_event(
            session,
            tenant_id=principal.tenant_id,
            aggregate_type="education_batch",
            aggregate_id=batch.id,
            event_type="education.batch.archived.v1",
            payload={
                "batchId": str(batch.id),
                "workspaceId": str(batch.workspace_id),
                "courseId": str(batch.course_id),
                "code": batch.code,
            },
        )
        await session.commit()
    return Response(status_code=204)
