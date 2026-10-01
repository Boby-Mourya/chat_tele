from __future__ import annotations

import hashlib
import uuid
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.education_access_request_schemas import (
    EducationAccessRequestAccepted,
    EducationAccessRequestCreate,
    EducationAccessRequestOut,
    EducationAccessRequestReview,
)
from northstar_api.education_access_requests import (
    EducationAccessRequest,
    EducationAccessRequestStatus,
)
from northstar_api.security import Principal
from northstar_api.services.education_access_requests import (
    EducationAccessRequestReviewError,
    create_education_access_request,
    review_education_access_request,
)
from northstar_api.services.rate_limit import redis_services

router = APIRouter(prefix="/education/access-requests", tags=["education"])
DB = Annotated[AsyncSession, Depends(get_session)]
EducationViewPrincipal = Annotated[Principal, Depends(require_permissions("education.view"))]
EducationManagePrincipal = Annotated[Principal, Depends(require_permissions("education.manage"))]
_START_WINDOW_SECONDS = 3600
_START_SOURCE_LIMIT = 30
_START_PROOF_LIMIT = 5


def _workspace_id(principal: Principal) -> UUID:
    if principal.workspace_id is None:
        raise HTTPException(status_code=403, detail="Workspace access is unavailable")
    return principal.workspace_id


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def _source(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def _limit(key: str, limit: int, window: int, scope: str) -> None:
    result = await redis_services.check_rate_limit(key, limit, window, scope=scope)
    if not result.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many education access requests. Try again later.",
            headers={"Retry-After": str(result.retry_after)},
        )


async def _enforce_start_rate_limit(payload: EducationAccessRequestCreate, request: Request) -> None:
    proof = "|".join(
        [
            payload.agent_public_id,
            payload.student_number,
            str(payload.email),
            payload.identity_type.value,
            payload.identifier,
        ]
    )
    await _limit(
        f"education-access-request:start:source:{_hash(_source(request))}",
        _START_SOURCE_LIMIT,
        _START_WINDOW_SECONDS,
        "education_access_request_start_source",
    )
    await _limit(
        f"education-access-request:start:proof:{_hash(proof)}",
        _START_PROOF_LIMIT,
        _START_WINDOW_SECONDS,
        "education_access_request_start_proof",
    )


def _request_out(value: EducationAccessRequest) -> EducationAccessRequestOut:
    return EducationAccessRequestOut.model_validate(value)


@router.post("", response_model=EducationAccessRequestAccepted, status_code=202)
async def create_access_request(
    payload: EducationAccessRequestCreate,
    request: Request,
    session: DB,
) -> EducationAccessRequestAccepted:
    """Create a support request without becoming a Student/enrollment existence oracle."""

    await _enforce_start_rate_limit(payload, request)
    request_id = uuid.uuid4()
    created = await create_education_access_request(
        session,
        request_id=request_id,
        agent_public_id=payload.agent_public_id,
        student_number=payload.student_number,
        email=str(payload.email),
        identity_type=payload.identity_type,
        identifier=payload.identifier,
        message=payload.message,
    )
    if created is not None:
        await session.commit()
    else:
        await session.rollback()
    return EducationAccessRequestAccepted(request_id=request_id)


@router.get("", response_model=list[EducationAccessRequestOut])
async def list_access_requests(
    principal: EducationViewPrincipal,
    session: DB,
    request_status: EducationAccessRequestStatus | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None, max_length=160),
) -> list[EducationAccessRequestOut]:
    workspace_id = _workspace_id(principal)
    conditions = [
        EducationAccessRequest.tenant_id == principal.tenant_id,
        EducationAccessRequest.workspace_id == workspace_id,
    ]
    if request_status is not None:
        conditions.append(EducationAccessRequest.status == request_status.value)
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        conditions.append(
            or_(
                EducationAccessRequest.student_number.ilike(pattern),
                EducationAccessRequest.email.ilike(pattern),
                EducationAccessRequest.normalized_identifier.ilike(pattern),
                EducationAccessRequest.message.ilike(pattern),
            )
        )
    values = (
        await session.scalars(
            select(EducationAccessRequest)
            .where(*conditions)
            .order_by(
                EducationAccessRequest.status,
                EducationAccessRequest.created_at.desc(),
            )
        )
    ).all()
    return [_request_out(value) for value in values]


@router.patch("/{request_id}", response_model=EducationAccessRequestOut)
async def review_access_request(
    request_id: UUID,
    payload: EducationAccessRequestReview,
    principal: EducationManagePrincipal,
    session: DB,
) -> EducationAccessRequestOut:
    workspace_id = _workspace_id(principal)
    try:
        value = await review_education_access_request(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=workspace_id,
            request_id=request_id,
            reviewer_user_id=principal.user_id,
            action=payload.action,
            student_id=payload.student_id,
            enrollment_id=payload.enrollment_id,
            note=payload.note,
        )
        await session.commit()
        await session.refresh(value)
    except EducationAccessRequestReviewError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None
    return _request_out(value)
