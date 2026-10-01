from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.education import CourseStatus, EducationCourse
from northstar_api.education_batches import EducationBatch
from northstar_api.education_catalog_schemas import (
    CurriculumCreate,
    CurriculumOut,
    CurriculumPatch,
    PaperCreate,
    PaperOut,
    PaperPatch,
)
from northstar_api.education_curricula import CurriculumStatus, EducationCurriculum
from northstar_api.education_papers import EducationPaper, PaperStatus
from northstar_api.security import Principal
from northstar_api.services.outbox import enqueue_event

router = APIRouter(prefix="/education", tags=["education"])
DB = Annotated[AsyncSession, Depends(get_session)]
EducationViewPrincipal = Annotated[Principal, Depends(require_permissions("education.view"))]
EducationManagePrincipal = Annotated[Principal, Depends(require_permissions("education.manage"))]


def _workspace_id(principal: Principal) -> UUID:
    if principal.workspace_id is None:
        raise HTTPException(status_code=403, detail="Workspace access is unavailable")
    return principal.workspace_id


async def _course(
    session: AsyncSession,
    *,
    principal: Principal,
    course_id: UUID,
    active: bool = False,
) -> EducationCourse:
    workspace_id = _workspace_id(principal)
    course = await session.scalar(
        select(EducationCourse).where(
            EducationCourse.id == course_id,
            EducationCourse.tenant_id == principal.tenant_id,
            EducationCourse.workspace_id == workspace_id,
        )
    )
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found")
    if active and course.status != CourseStatus.ACTIVE.value:
        raise HTTPException(status_code=409, detail="Course is archived")
    return course


async def _curriculum(
    session: AsyncSession,
    *,
    principal: Principal,
    curriculum_id: UUID,
    active: bool = False,
) -> EducationCurriculum:
    workspace_id = _workspace_id(principal)
    curriculum = await session.scalar(
        select(EducationCurriculum).where(
            EducationCurriculum.id == curriculum_id,
            EducationCurriculum.tenant_id == principal.tenant_id,
            EducationCurriculum.workspace_id == workspace_id,
        )
    )
    if curriculum is None:
        raise HTTPException(status_code=404, detail="Curriculum not found")
    if active and curriculum.status != CurriculumStatus.ACTIVE.value:
        raise HTTPException(status_code=409, detail="Curriculum is archived")
    return curriculum


async def _paper(session: AsyncSession, *, principal: Principal, paper_id: UUID) -> EducationPaper:
    workspace_id = _workspace_id(principal)
    paper = await session.scalar(
        select(EducationPaper).where(
            EducationPaper.id == paper_id,
            EducationPaper.tenant_id == principal.tenant_id,
            EducationPaper.workspace_id == workspace_id,
        )
    )
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    return paper


def _validate_dates(start: date | None, end: date | None) -> None:
    if start and end and end < start:
        raise HTTPException(status_code=422, detail="Curriculum effective end cannot be before its start")


@router.get("/curricula", response_model=list[CurriculumOut])
async def list_curricula(
    principal: EducationViewPrincipal,
    session: DB,
    course_id: UUID | None = Query(default=None),
    curriculum_status: CurriculumStatus | None = Query(default=None, alias="status"),
) -> list[CurriculumOut]:
    conditions = [
        EducationCurriculum.tenant_id == principal.tenant_id,
        EducationCurriculum.workspace_id == _workspace_id(principal),
    ]
    if course_id:
        conditions.append(EducationCurriculum.course_id == course_id)
    if curriculum_status:
        conditions.append(EducationCurriculum.status == curriculum_status.value)
    rows = (
        await session.scalars(
            select(EducationCurriculum)
            .where(*conditions)
            .order_by(EducationCurriculum.course_id, EducationCurriculum.version)
        )
    ).all()
    return [CurriculumOut.model_validate(row) for row in rows]


@router.post("/curricula", response_model=CurriculumOut, status_code=201)
async def create_curriculum(
    payload: CurriculumCreate,
    principal: EducationManagePrincipal,
    session: DB,
) -> CurriculumOut:
    course = await _course(session, principal=principal, course_id=payload.course_id, active=True)
    row = EducationCurriculum(
        tenant_id=principal.tenant_id,
        workspace_id=course.workspace_id,
        course_id=course.id,
        version=payload.version,
        name=payload.name,
        description=payload.description,
        effective_from=payload.effective_from,
        effective_to=payload.effective_to,
        status=CurriculumStatus.ACTIVE.value,
    )
    session.add(row)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="This curriculum version already exists") from None
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="education_curriculum",
        aggregate_id=row.id,
        event_type="education.curriculum.created.v1",
        payload={"curriculumId": str(row.id), "courseId": str(row.course_id), "version": row.version},
    )
    await session.commit()
    await session.refresh(row)
    return CurriculumOut.model_validate(row)


@router.patch("/curricula/{curriculum_id}", response_model=CurriculumOut)
async def update_curriculum(
    curriculum_id: UUID,
    payload: CurriculumPatch,
    principal: EducationManagePrincipal,
    session: DB,
) -> CurriculumOut:
    row = await _curriculum(session, principal=principal, curriculum_id=curriculum_id)
    next_start = payload.effective_from if "effective_from" in payload.model_fields_set else row.effective_from
    next_end = payload.effective_to if "effective_to" in payload.model_fields_set else row.effective_to
    _validate_dates(next_start, next_end)
    if payload.status == CurriculumStatus.ARCHIVED:
        active_batch = await session.scalar(
            select(EducationBatch.id)
            .where(EducationBatch.curriculum_id == row.id, EducationBatch.status == "active")
            .limit(1)
        )
        if active_batch:
            raise HTTPException(status_code=409, detail="Archive active batches before this curriculum")
    for field in payload.model_fields_set:
        value = getattr(payload, field)
        if field == "status" and value is not None:
            value = value.value
        setattr(row, field, value)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="This curriculum version already exists") from None
    await session.refresh(row)
    return CurriculumOut.model_validate(row)


@router.delete("/curricula/{curriculum_id}", status_code=204)
async def archive_curriculum(
    curriculum_id: UUID,
    principal: EducationManagePrincipal,
    session: DB,
) -> Response:
    await update_curriculum(
        curriculum_id,
        CurriculumPatch(status=CurriculumStatus.ARCHIVED),
        principal,
        session,
    )
    return Response(status_code=204)


@router.get("/papers", response_model=list[PaperOut])
async def list_papers(
    principal: EducationViewPrincipal,
    session: DB,
    course_id: UUID | None = Query(default=None),
    curriculum_id: UUID | None = Query(default=None),
    paper_status: PaperStatus | None = Query(default=None, alias="status"),
) -> list[PaperOut]:
    conditions = [
        EducationPaper.tenant_id == principal.tenant_id,
        EducationPaper.workspace_id == _workspace_id(principal),
    ]
    if course_id:
        conditions.append(EducationPaper.course_id == course_id)
    if curriculum_id:
        conditions.append(EducationPaper.curriculum_id == curriculum_id)
    if paper_status:
        conditions.append(EducationPaper.status == paper_status.value)
    rows = (
        await session.scalars(
            select(EducationPaper)
            .where(*conditions)
            .order_by(EducationPaper.course_id, EducationPaper.sequence, EducationPaper.name)
        )
    ).all()
    return [PaperOut.model_validate(row) for row in rows]


@router.post("/papers", response_model=PaperOut, status_code=201)
async def create_paper(
    payload: PaperCreate,
    principal: EducationManagePrincipal,
    session: DB,
) -> PaperOut:
    curriculum = await _curriculum(
        session, principal=principal, curriculum_id=payload.curriculum_id, active=True
    )
    await _course(session, principal=principal, course_id=curriculum.course_id, active=True)
    row = EducationPaper(
        tenant_id=principal.tenant_id,
        workspace_id=curriculum.workspace_id,
        course_id=curriculum.course_id,
        curriculum_id=curriculum.id,
        code=payload.code,
        name=payload.name,
        description=payload.description,
        aliases=payload.aliases,
        sequence=payload.sequence,
        status=PaperStatus.ACTIVE.value,
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="This paper code already exists in the curriculum") from None
    await session.refresh(row)
    return PaperOut.model_validate(row)


@router.patch("/papers/{paper_id}", response_model=PaperOut)
async def update_paper(
    paper_id: UUID,
    payload: PaperPatch,
    principal: EducationManagePrincipal,
    session: DB,
) -> PaperOut:
    row = await _paper(session, principal=principal, paper_id=paper_id)
    for field in payload.model_fields_set:
        value = getattr(payload, field)
        if field == "status" and value is not None:
            value = value.value
        setattr(row, field, value)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="This paper code already exists in the curriculum") from None
    await session.refresh(row)
    return PaperOut.model_validate(row)


@router.delete("/papers/{paper_id}", status_code=204)
async def archive_paper(
    paper_id: UUID,
    principal: EducationManagePrincipal,
    session: DB,
) -> Response:
    await update_paper(
        paper_id,
        PaperPatch(status=PaperStatus.ARCHIVED),
        principal,
        session,
    )
    return Response(status_code=204)
