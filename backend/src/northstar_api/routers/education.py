from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.education import CourseStatus, EducationCourse
from northstar_api.education_batches import BatchStatus, EducationBatch
from northstar_api.education_schemas import CourseCreate, CourseOut, CoursePatch
from northstar_api.security import Principal
from northstar_api.services.education_enrollment import has_non_terminal_enrollment
from northstar_api.services.outbox import enqueue_event

router = APIRouter(prefix="/education/courses", tags=["education"])
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
    return course


async def _ensure_course_has_no_active_batches(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    course_id: UUID,
) -> None:
    active_batch_id = await session.scalar(
        select(EducationBatch.id)
        .where(
            EducationBatch.tenant_id == tenant_id,
            EducationBatch.workspace_id == workspace_id,
            EducationBatch.course_id == course_id,
            EducationBatch.status == BatchStatus.ACTIVE.value,
        )
        .limit(1)
    )
    if active_batch_id is not None:
        raise HTTPException(
            status_code=409,
            detail="Archive active batches before archiving this course",
        )


async def _ensure_course_has_no_live_enrollments(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    course_id: UUID,
) -> None:
    if await has_non_terminal_enrollment(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        course_id=course_id,
    ):
        raise HTTPException(
            status_code=409,
            detail="Resolve non-terminal Enrollments before archiving this Course",
        )


def _course_out(course: EducationCourse) -> CourseOut:
    return CourseOut.model_validate(course)


@router.get("", response_model=list[CourseOut])
async def list_courses(
    principal: EducationViewPrincipal,
    session: DB,
    course_status: CourseStatus | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None, max_length=120),
) -> list[CourseOut]:
    workspace_id = _workspace_id(principal)
    conditions = [
        EducationCourse.tenant_id == principal.tenant_id,
        EducationCourse.workspace_id == workspace_id,
    ]
    if course_status is not None:
        conditions.append(EducationCourse.status == course_status.value)
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        conditions.append(
            or_(
                EducationCourse.code.ilike(pattern),
                EducationCourse.name.ilike(pattern),
                EducationCourse.description.ilike(pattern),
            )
        )
    courses = (
        await session.scalars(
            select(EducationCourse)
            .where(*conditions)
            .order_by(EducationCourse.status, EducationCourse.name, EducationCourse.code)
        )
    ).all()
    return [_course_out(course) for course in courses]


@router.post("", response_model=CourseOut, status_code=201)
async def create_course(
    payload: CourseCreate,
    principal: EducationManagePrincipal,
    session: DB,
) -> CourseOut:
    workspace_id = _workspace_id(principal)
    course = EducationCourse(
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        code=payload.code,
        name=payload.name,
        awarding_body=payload.awarding_body,
        jurisdiction=payload.jurisdiction,
        aliases=payload.aliases,
        description=payload.description,
        status=CourseStatus.ACTIVE.value,
    )
    session.add(course)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="A course with this code already exists in this workspace",
        ) from None
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="education_course",
        aggregate_id=course.id,
        event_type="education.course.created.v1",
        payload={
            "courseId": str(course.id),
            "workspaceId": str(workspace_id),
            "code": course.code,
            "name": course.name,
        },
    )
    await session.commit()
    await session.refresh(course)
    return _course_out(course)


@router.get("/{course_id}", response_model=CourseOut)
async def get_course(
    course_id: UUID,
    principal: EducationViewPrincipal,
    session: DB,
) -> CourseOut:
    return _course_out(
        await _scoped_course(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=_workspace_id(principal),
            course_id=course_id,
        )
    )


@router.patch("/{course_id}", response_model=CourseOut)
async def update_course(
    course_id: UUID,
    payload: CoursePatch,
    principal: EducationManagePrincipal,
    session: DB,
) -> CourseOut:
    workspace_id = _workspace_id(principal)
    course = await _scoped_course(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        course_id=course_id,
    )
    if payload.status == CourseStatus.ARCHIVED and course.status != CourseStatus.ARCHIVED.value:
        await _ensure_course_has_no_live_enrollments(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=workspace_id,
            course_id=course.id,
        )
        await _ensure_course_has_no_active_batches(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=workspace_id,
            course_id=course.id,
        )

    changed_fields: list[str] = []
    for field_name in payload.model_fields_set:
        value = getattr(payload, field_name)
        if value is None:
            continue
        if field_name == "status":
            value = value.value
        if getattr(course, field_name) == value:
            continue
        setattr(course, field_name, value)
        changed_fields.append(field_name)

    if not changed_fields:
        return _course_out(course)

    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="education_course",
        aggregate_id=course.id,
        event_type="education.course.updated.v1",
        payload={
            "courseId": str(course.id),
            "workspaceId": str(course.workspace_id),
            "fields": sorted(changed_fields),
            "status": course.status,
        },
    )
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="A course with this code already exists in this workspace",
        ) from None
    await session.refresh(course)
    return _course_out(course)


@router.delete("/{course_id}", status_code=204)
async def archive_course(
    course_id: UUID,
    principal: EducationManagePrincipal,
    session: DB,
) -> Response:
    workspace_id = _workspace_id(principal)
    course = await _scoped_course(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        course_id=course_id,
    )
    if course.status != CourseStatus.ARCHIVED.value:
        await _ensure_course_has_no_live_enrollments(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=workspace_id,
            course_id=course.id,
        )
        await _ensure_course_has_no_active_batches(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=workspace_id,
            course_id=course.id,
        )
        course.status = CourseStatus.ARCHIVED.value
        enqueue_event(
            session,
            tenant_id=principal.tenant_id,
            aggregate_type="education_course",
            aggregate_id=course.id,
            event_type="education.course.archived.v1",
            payload={
                "courseId": str(course.id),
                "workspaceId": str(course.workspace_id),
                "code": course.code,
            },
        )
        await session.commit()
    return Response(status_code=204)
