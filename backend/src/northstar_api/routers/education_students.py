from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.education_student_schemas import StudentCreate, StudentOut, StudentPatch
from northstar_api.education_students import EducationStudent, StudentStatus
from northstar_api.security import Principal
from northstar_api.services.education_enrollment import has_non_terminal_enrollment
from northstar_api.services.outbox import enqueue_event

router = APIRouter(prefix="/education/students", tags=["education"])
DB = Annotated[AsyncSession, Depends(get_session)]
EducationViewPrincipal = Annotated[Principal, Depends(require_permissions("education.view"))]
EducationManagePrincipal = Annotated[Principal, Depends(require_permissions("education.manage"))]


def _workspace_id(principal: Principal) -> UUID:
    if principal.workspace_id is None:
        raise HTTPException(status_code=403, detail="Workspace access is unavailable")
    return principal.workspace_id


async def _scoped_student(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    student_id: UUID,
) -> EducationStudent:
    student = await session.scalar(
        select(EducationStudent).where(
            EducationStudent.id == student_id,
            EducationStudent.tenant_id == tenant_id,
            EducationStudent.workspace_id == workspace_id,
        )
    )
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    return student


async def _ensure_student_has_no_live_enrollments(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    student_id: UUID,
) -> None:
    if await has_non_terminal_enrollment(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        student_id=student_id,
    ):
        raise HTTPException(
            status_code=409,
            detail="Resolve non-terminal Enrollments before archiving this Student",
        )


async def _student_out(student: EducationStudent, session: AsyncSession) -> StudentOut:
    from northstar_api.education_student_identities import EducationStudentIdentity

    identity = await session.scalar(
        select(EducationStudentIdentity)
        .where(
            EducationStudentIdentity.student_id == student.id,
            EducationStudentIdentity.workspace_id == student.workspace_id,
            EducationStudentIdentity.identity_type == "whatsapp",
            EducationStudentIdentity.status != "revoked",
        )
        .order_by(EducationStudentIdentity.is_primary.desc(), EducationStudentIdentity.created_at)
        .limit(1)
    )
    telegram_identity = await session.scalar(
        select(EducationStudentIdentity)
        .where(
            EducationStudentIdentity.student_id == student.id,
            EducationStudentIdentity.workspace_id == student.workspace_id,
            EducationStudentIdentity.identity_type == "telegram",
            EducationStudentIdentity.status != "revoked",
        )
        .order_by(EducationStudentIdentity.is_primary.desc(), EducationStudentIdentity.created_at)
        .limit(1)
    )
    result = StudentOut.model_validate(student)
    result.whatsapp_number = identity.normalized_identifier if identity else None
    result.whatsapp_verified = bool(identity and identity.status == "verified")
    result.telegram_user_id = telegram_identity.normalized_identifier if telegram_identity else None
    result.telegram_verified = bool(telegram_identity and telegram_identity.status == "verified")
    return result


async def _save_whatsapp(session, student, number, verified):
    from datetime import UTC, datetime

    from northstar_api.education_student_identities import EducationStudentIdentity

    identities = (
        await session.scalars(
            select(EducationStudentIdentity)
            .where(
                EducationStudentIdentity.student_id == student.id,
                EducationStudentIdentity.workspace_id == student.workspace_id,
                EducationStudentIdentity.identity_type == "whatsapp",
            )
            .with_for_update()
        )
    ).all()
    target = next((item for item in identities if item.normalized_identifier == number), None)
    for item in identities:
        if item.is_primary and item is not target:
            item.is_primary = False
            item.status = "revoked"
    if number:
        if target is None:
            target = EducationStudentIdentity(
                tenant_id=student.tenant_id,
                workspace_id=student.workspace_id,
                student_id=student.id,
                identity_type="whatsapp",
                identifier=number,
                normalized_identifier=number,
            )
            session.add(target)
        target.is_primary = True
        target.status = "verified" if verified else "pending"
        target.verified_at = datetime.now(UTC) if verified else None
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            409, "This WhatsApp number is already linked to another student in this workspace"
        ) from None
    enqueue_event(
        session,
        tenant_id=student.tenant_id,
        aggregate_type="education_student",
        aggregate_id=student.id,
        event_type="education.student.whatsapp.updated.v1",
        payload={"studentId": str(student.id), "verified": verified},
    )


async def _save_telegram(session, student, user_id, verified):
    from datetime import UTC, datetime

    from northstar_api.education_student_identities import EducationStudentIdentity

    identities = (
        await session.scalars(
            select(EducationStudentIdentity)
            .where(
                EducationStudentIdentity.student_id == student.id,
                EducationStudentIdentity.workspace_id == student.workspace_id,
                EducationStudentIdentity.identity_type == "telegram",
            )
            .with_for_update()
        )
    ).all()
    target = next((item for item in identities if item.normalized_identifier == user_id), None)
    for item in identities:
        if item.is_primary and item is not target:
            item.is_primary = False
            item.status = "revoked"
            item.verified_at = None
    if user_id:
        if target is None:
            target = EducationStudentIdentity(
                tenant_id=student.tenant_id,
                workspace_id=student.workspace_id,
                student_id=student.id,
                identity_type="telegram",
                identifier=user_id,
                normalized_identifier=user_id,
            )
            session.add(target)
        target.is_primary = True
        target.status = "verified" if verified else "pending"
        target.verified_at = datetime.now(UTC) if verified else None
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            409, "This Telegram user ID is already linked to another student in this workspace"
        ) from None
    enqueue_event(
        session,
        tenant_id=student.tenant_id,
        aggregate_type="education_student",
        aggregate_id=student.id,
        event_type="education.student.telegram.updated.v1",
        payload={"studentId": str(student.id), "configured": bool(user_id), "verified": bool(user_id and verified)},
    )


@router.get("", response_model=list[StudentOut])
async def list_students(
    principal: EducationViewPrincipal,
    session: DB,
    student_status: StudentStatus | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None, max_length=160),
) -> list[StudentOut]:
    workspace_id = _workspace_id(principal)
    conditions = [
        EducationStudent.tenant_id == principal.tenant_id,
        EducationStudent.workspace_id == workspace_id,
    ]
    if student_status is not None:
        conditions.append(EducationStudent.status == student_status.value)
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        conditions.append(
            or_(
                EducationStudent.student_number.ilike(pattern),
                EducationStudent.name.ilike(pattern),
                EducationStudent.email.ilike(pattern),
            )
        )
    students = (
        await session.scalars(
            select(EducationStudent)
            .where(*conditions)
            .order_by(EducationStudent.status, EducationStudent.name, EducationStudent.student_number)
        )
    ).all()
    return [await _student_out(student, session) for student in students]


@router.post("", response_model=StudentOut, status_code=201)
async def create_student(
    payload: StudentCreate,
    principal: EducationManagePrincipal,
    session: DB,
) -> StudentOut:
    workspace_id = _workspace_id(principal)
    student = EducationStudent(
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        telegram_phone_number=payload.telegram_phone_number,
        telegram_phone_verified=bool(payload.telegram_phone_number and payload.telegram_phone_verified),
        student_number=payload.student_number,
        name=payload.name,
        email=str(payload.email) if payload.email is not None else None,
        preferred_language=payload.preferred_language,
        custom_fields=payload.custom_fields,
        status=StudentStatus.ACTIVE.value,
    )
    session.add(student)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="A student with this Student ID or Telegram phone number already exists in this workspace",
        ) from None
    if payload.whatsapp_number:
        await _save_whatsapp(session, student, payload.whatsapp_number, payload.whatsapp_verified)
    if payload.telegram_user_id:
        await _save_telegram(session, student, payload.telegram_user_id, payload.telegram_verified)
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="education_student",
        aggregate_id=student.id,
        event_type="education.student.created.v1",
        payload={
            "studentId": str(student.id),
            "workspaceId": str(workspace_id),
            "studentNumber": student.student_number,
            "name": student.name,
        },
    )
    await session.commit()
    await session.refresh(student)
    return await _student_out(student, session)


@router.get("/{student_id}", response_model=StudentOut)
async def get_student(
    student_id: UUID,
    principal: EducationViewPrincipal,
    session: DB,
) -> StudentOut:
    return await _student_out(
        await _scoped_student(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=_workspace_id(principal),
            student_id=student_id,
        ),
        session,
    )


@router.patch("/{student_id}", response_model=StudentOut)
async def update_student(
    student_id: UUID,
    payload: StudentPatch,
    principal: EducationManagePrincipal,
    session: DB,
) -> StudentOut:
    workspace_id = _workspace_id(principal)
    student = await _scoped_student(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        student_id=student_id,
    )
    if payload.status == StudentStatus.ARCHIVED and student.status != StudentStatus.ARCHIVED.value:
        await _ensure_student_has_no_live_enrollments(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=workspace_id,
            student_id=student.id,
        )

    # Serialize phone changes with contact verification before touching account bindings.
    await session.refresh(student, with_for_update=True)
    changed_fields: list[str] = []
    if "telegram_phone_number" in payload.model_fields_set and payload.telegram_phone_number != student.telegram_phone_number:
        from northstar_api.education_student_identities import EducationStudentIdentity
        identities = (await session.scalars(select(EducationStudentIdentity).where(
            EducationStudentIdentity.tenant_id == student.tenant_id,
            EducationStudentIdentity.workspace_id == student.workspace_id,
            EducationStudentIdentity.student_id == student.id,
            EducationStudentIdentity.identity_type == "telegram",
        ).with_for_update())).all()
        for identity in identities:
            if identity.status != "revoked":
                identity.status = "pending"
            identity.is_primary = False
            identity.verified_at = None
        student.telegram_phone_verified = False
        changed_fields.append("telegram_phone_verified")
        student.telegram_phone_number = payload.telegram_phone_number
        changed_fields.append("telegram_phone_number")
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            raise HTTPException(409, "This Telegram phone number is already assigned in this workspace") from None

    if "whatsapp_number" in payload.model_fields_set:
        await _save_whatsapp(session, student, payload.whatsapp_number, payload.whatsapp_verified)
        changed_fields.append("whatsapp_number")
    if "telegram_user_id" in payload.model_fields_set:
        await _save_telegram(session, student, payload.telegram_user_id, payload.telegram_verified)
        changed_fields.append("telegram_user_id")
    if "telegram_phone_verified" in payload.model_fields_set:
        confirmed = bool(student.telegram_phone_number and payload.telegram_phone_verified)
        if student.telegram_phone_verified != confirmed:
            student.telegram_phone_verified = confirmed
            changed_fields.append("telegram_phone_verified")
    for field_name in payload.model_fields_set:
        if field_name in {"telegram_phone_verified", "telegram_phone_number", "whatsapp_number", "whatsapp_verified", "telegram_user_id", "telegram_verified"}:
            continue
        value = getattr(payload, field_name)
        if field_name != "email" and value is None:
            continue
        if field_name == "status" and value is not None:
            value = value.value
        if field_name == "email" and value is not None:
            value = str(value)
        if getattr(student, field_name) == value:
            continue
        setattr(student, field_name, value)
        changed_fields.append(field_name)

    if not changed_fields:
        return await _student_out(student, session)

    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="education_student",
        aggregate_id=student.id,
        event_type="education.student.updated.v1",
        payload={
            "studentId": str(student.id),
            "workspaceId": str(student.workspace_id),
            "fields": sorted(changed_fields),
            "status": student.status,
        },
    )
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="A student with this Student ID or Telegram phone number already exists in this workspace",
        ) from None
    await session.refresh(student)
    return await _student_out(student, session)


@router.delete("/{student_id}", status_code=204)
async def archive_student(
    student_id: UUID,
    principal: EducationManagePrincipal,
    session: DB,
) -> Response:
    workspace_id = _workspace_id(principal)
    student = await _scoped_student(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        student_id=student_id,
    )
    if student.status != StudentStatus.ARCHIVED.value:
        await _ensure_student_has_no_live_enrollments(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=workspace_id,
            student_id=student.id,
        )
        student.status = StudentStatus.ARCHIVED.value
        enqueue_event(
            session,
            tenant_id=principal.tenant_id,
            aggregate_type="education_student",
            aggregate_id=student.id,
            event_type="education.student.archived.v1",
            payload={
                "studentId": str(student.id),
                "workspaceId": str(student.workspace_id),
                "studentNumber": student.student_number,
            },
        )
        await session.commit()
    return Response(status_code=204)
