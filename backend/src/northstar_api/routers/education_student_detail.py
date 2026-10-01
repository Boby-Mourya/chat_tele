from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.education_student_detail_schemas import StudentDetailOut
from northstar_api.security import Principal
from northstar_api.services.education_student_detail import (
    StudentDetailNotFoundError,
    get_student_detail,
)

router = APIRouter(prefix="/education/students", tags=["education"])
DB = Annotated[AsyncSession, Depends(get_session)]
EducationViewPrincipal = Annotated[Principal, Depends(require_permissions("education.view"))]


def _workspace_id(principal: Principal) -> UUID:
    if principal.workspace_id is None:
        raise HTTPException(status_code=403, detail="Workspace access is unavailable")
    return principal.workspace_id


@router.get("/{student_id}/detail", response_model=StudentDetailOut)
async def student_detail(
    student_id: UUID,
    principal: EducationViewPrincipal,
    session: DB,
    activity_limit: int = Query(default=100, ge=1, le=500),
) -> StudentDetailOut:
    try:
        return await get_student_detail(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=_workspace_id(principal),
            student_id=student_id,
            activity_limit=activity_limit,
        )
    except StudentDetailNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Student not found") from exc
