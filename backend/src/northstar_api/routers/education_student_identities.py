from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.education_student_identities import (
    EducationStudentIdentity,
    StudentIdentityStatus,
    StudentIdentityType,
)
from northstar_api.education_student_identity_schemas import (
    StudentIdentityCreate,
    StudentIdentityOut,
    StudentIdentityPatch,
)
from northstar_api.education_students import EducationStudent, StudentStatus
from northstar_api.security import Principal
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


async def _scoped_identity(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    student_id: UUID,
    identity_id: UUID,
) -> EducationStudentIdentity:
    identity = await session.scalar(
        select(EducationStudentIdentity).where(
            EducationStudentIdentity.id == identity_id,
            EducationStudentIdentity.student_id == student_id,
            EducationStudentIdentity.tenant_id == tenant_id,
            EducationStudentIdentity.workspace_id == workspace_id,
        )
    )
    if identity is None:
        raise HTTPException(status_code=404, detail="Student identity not found")
    return identity


def _identity_out(identity: EducationStudentIdentity) -> StudentIdentityOut:
    return StudentIdentityOut.model_validate(identity)


async def _demote_other_primaries(
    session: AsyncSession,
    *,
    identity: EducationStudentIdentity,
) -> None:
    identities = (
        await session.scalars(
            select(EducationStudentIdentity).where(
                EducationStudentIdentity.student_id == identity.student_id,
                EducationStudentIdentity.identity_type == identity.identity_type,
                EducationStudentIdentity.id != identity.id,
                EducationStudentIdentity.status != StudentIdentityStatus.REVOKED.value,
                EducationStudentIdentity.is_primary.is_(True),
            )
        )
    ).all()
    for current in identities:
        current.is_primary = False


async def _ensure_primary_exists(
    session: AsyncSession,
    *,
    student_id: UUID,
    identity_type: str,
) -> None:
    primary = await session.scalar(
        select(EducationStudentIdentity.id).where(
            EducationStudentIdentity.student_id == student_id,
            EducationStudentIdentity.identity_type == identity_type,
            EducationStudentIdentity.status != StudentIdentityStatus.REVOKED.value,
            EducationStudentIdentity.is_primary.is_(True),
        )
    )
    if primary is not None:
        return
    replacement = await session.scalar(
        select(EducationStudentIdentity)
        .where(
            EducationStudentIdentity.student_id == student_id,
            EducationStudentIdentity.identity_type == identity_type,
            EducationStudentIdentity.status != StudentIdentityStatus.REVOKED.value,
        )
        .order_by(EducationStudentIdentity.created_at, EducationStudentIdentity.id)
    )
    if replacement is not None:
        replacement.is_primary = True


@router.get("/{student_id}/identities", response_model=list[StudentIdentityOut])
async def list_student_identities(
    student_id: UUID,
    principal: EducationViewPrincipal,
    session: DB,
    identity_status: StudentIdentityStatus | None = Query(default=None, alias="status"),
    identity_type: StudentIdentityType | None = Query(default=None, alias="type"),
) -> list[StudentIdentityOut]:
    workspace_id = _workspace_id(principal)
    await _scoped_student(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        student_id=student_id,
    )
    conditions = [
        EducationStudentIdentity.tenant_id == principal.tenant_id,
        EducationStudentIdentity.workspace_id == workspace_id,
        EducationStudentIdentity.student_id == student_id,
    ]
    if identity_status is not None:
        conditions.append(EducationStudentIdentity.status == identity_status.value)
    if identity_type is not None:
        conditions.append(EducationStudentIdentity.identity_type == identity_type.value)
    identities = (
        await session.scalars(
            select(EducationStudentIdentity)
            .where(*conditions)
            .order_by(
                EducationStudentIdentity.identity_type,
                EducationStudentIdentity.is_primary.desc(),
                EducationStudentIdentity.created_at,
            )
        )
    ).all()
    return [_identity_out(identity) for identity in identities]


@router.post("/{student_id}/identities", response_model=StudentIdentityOut, status_code=201)
async def create_student_identity(
    student_id: UUID,
    payload: StudentIdentityCreate,
    principal: EducationManagePrincipal,
    session: DB,
) -> StudentIdentityOut:
    workspace_id = _workspace_id(principal)
    student = await _scoped_student(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        student_id=student_id,
    )
    if student.status != StudentStatus.ACTIVE.value:
        raise HTTPException(status_code=409, detail="Reactivate the student before adding identities")

    has_identity = await session.scalar(
        select(EducationStudentIdentity.id).where(
            EducationStudentIdentity.student_id == student.id,
            EducationStudentIdentity.identity_type == payload.identity_type.value,
            EducationStudentIdentity.status != StudentIdentityStatus.REVOKED.value,
        )
    )
    identity = EducationStudentIdentity(
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        student_id=student.id,
        identity_type=payload.identity_type.value,
        identifier=payload.identifier,
        normalized_identifier=payload.identifier,
        label=payload.label,
        status=payload.status.value,
        is_primary=payload.is_primary or has_identity is None,
        verified_at=(datetime.now(UTC) if payload.status is StudentIdentityStatus.VERIFIED else None),
    )
    session.add(identity)
    try:
        await session.flush()
        if identity.is_primary:
            await _demote_other_primaries(session, identity=identity)
            await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="This identity is already linked to a student in this workspace",
        ) from None

    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="education_student_identity",
        aggregate_id=identity.id,
        event_type="education.student_identity.created.v1",
        payload={
            "identityId": str(identity.id),
            "studentId": str(student.id),
            "workspaceId": str(workspace_id),
            "identityType": identity.identity_type,
            "status": identity.status,
            "isPrimary": identity.is_primary,
        },
    )
    if identity.status == StudentIdentityStatus.VERIFIED.value:
        enqueue_event(
            session,
            tenant_id=principal.tenant_id,
            aggregate_type="education_student_identity",
            aggregate_id=identity.id,
            event_type="education.student_identity.verified.v1",
            payload={
                "identityId": str(identity.id),
                "studentId": str(student.id),
                "workspaceId": str(workspace_id),
                "identityType": identity.identity_type,
            },
        )
    await session.commit()
    await session.refresh(identity)
    return _identity_out(identity)


@router.patch("/{student_id}/identities/{identity_id}", response_model=StudentIdentityOut)
async def update_student_identity(
    student_id: UUID,
    identity_id: UUID,
    payload: StudentIdentityPatch,
    principal: EducationManagePrincipal,
    session: DB,
) -> StudentIdentityOut:
    workspace_id = _workspace_id(principal)
    await _scoped_student(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        student_id=student_id,
    )
    identity = await _scoped_identity(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        student_id=student_id,
        identity_id=identity_id,
    )
    previous_status = identity.status
    changed_fields: list[str] = []

    if "label" in payload.model_fields_set and identity.label != payload.label:
        identity.label = payload.label
        changed_fields.append("label")

    if "status" in payload.model_fields_set and payload.status is not None:
        next_status = payload.status.value
        if identity.status != next_status:
            identity.status = next_status
            changed_fields.append("status")
            if payload.status is StudentIdentityStatus.VERIFIED:
                identity.verified_at = datetime.now(UTC)
            elif payload.status is StudentIdentityStatus.PENDING:
                identity.verified_at = None
            if payload.status is StudentIdentityStatus.REVOKED:
                identity.is_primary = False

    if "is_primary" in payload.model_fields_set and payload.is_primary is not None:
        if payload.is_primary and identity.status == StudentIdentityStatus.REVOKED.value:
            raise HTTPException(status_code=422, detail="A revoked identity cannot be primary")
        if identity.is_primary != payload.is_primary:
            identity.is_primary = payload.is_primary
            changed_fields.append("is_primary")

    if identity.is_primary:
        await _demote_other_primaries(session, identity=identity)
    else:
        # The shared session has autoflush disabled. Persist the identity's new
        # status/primary state before querying for a replacement, otherwise the
        # database can still report this identity as the current primary.
        await session.flush()
        await _ensure_primary_exists(
            session,
            student_id=student_id,
            identity_type=identity.identity_type,
        )

    if not changed_fields:
        return _identity_out(identity)

    event_type = "education.student_identity.updated.v1"
    if identity.status != previous_status:
        if identity.status == StudentIdentityStatus.VERIFIED.value:
            event_type = "education.student_identity.verified.v1"
        elif identity.status == StudentIdentityStatus.REVOKED.value:
            event_type = "education.student_identity.revoked.v1"

    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="education_student_identity",
        aggregate_id=identity.id,
        event_type=event_type,
        payload={
            "identityId": str(identity.id),
            "studentId": str(student_id),
            "workspaceId": str(workspace_id),
            "identityType": identity.identity_type,
            "status": identity.status,
            "isPrimary": identity.is_primary,
            "fields": sorted(changed_fields),
        },
    )
    await session.commit()
    await session.refresh(identity)
    return _identity_out(identity)


@router.delete("/{student_id}/identities/{identity_id}", status_code=204)
async def revoke_student_identity(
    student_id: UUID,
    identity_id: UUID,
    principal: EducationManagePrincipal,
    session: DB,
) -> Response:
    workspace_id = _workspace_id(principal)
    await _scoped_student(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        student_id=student_id,
    )
    identity = await _scoped_identity(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        student_id=student_id,
        identity_id=identity_id,
    )
    if identity.status != StudentIdentityStatus.REVOKED.value:
        identity.status = StudentIdentityStatus.REVOKED.value
        identity.is_primary = False
        # Flush first because AsyncSession is configured with autoflush=False;
        # primary failover must query against the newly revoked state.
        await session.flush()
        await _ensure_primary_exists(
            session,
            student_id=student_id,
            identity_type=identity.identity_type,
        )
        enqueue_event(
            session,
            tenant_id=principal.tenant_id,
            aggregate_type="education_student_identity",
            aggregate_id=identity.id,
            event_type="education.student_identity.revoked.v1",
            payload={
                "identityId": str(identity.id),
                "studentId": str(student_id),
                "workspaceId": str(workspace_id),
                "identityType": identity.identity_type,
            },
        )
        await session.commit()
    return Response(status_code=204)
