from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.education_student_import_schemas import (
    StudentImportCommitResponse,
    StudentImportPayload,
    StudentImportPreview,
)
from northstar_api.security import Principal
from northstar_api.services.education_student_import import (
    StudentImportConflictError,
    commit_student_import,
    validate_student_import,
)
from northstar_api.services.education_student_import_file import (
    StudentImportFileError,
    parse_student_import_file,
)

router = APIRouter(prefix="/education/students/import", tags=["education"])
DB = Annotated[AsyncSession, Depends(get_session)]
EducationManagePrincipal = Annotated[Principal, Depends(require_permissions("education.manage"))]
_MAX_IMPORT_FILE_BYTES = 2_000_000


def _workspace_id(principal: Principal) -> UUID:
    if principal.workspace_id is None:
        raise HTTPException(status_code=403, detail="Workspace access is unavailable")
    return principal.workspace_id


@router.post("/parse-file", response_model=StudentImportPayload)
async def parse_student_import_upload(
    principal: EducationManagePrincipal,
    file: UploadFile = File(...),
) -> StudentImportPayload:
    del principal  # Permission dependency is the authorization boundary for this parser endpoint.
    filename = file.filename or "students.csv"
    content = await file.read(_MAX_IMPORT_FILE_BYTES + 1)
    await file.close()
    if len(content) > _MAX_IMPORT_FILE_BYTES:
        raise HTTPException(status_code=413, detail="Import file must be 2 MB or smaller")
    try:
        rows = parse_student_import_file(filename, content)
    except StudentImportFileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return StudentImportPayload(rows=rows)


@router.post("/preview", response_model=StudentImportPreview)
async def preview_student_import(
    payload: StudentImportPayload,
    principal: EducationManagePrincipal,
    session: DB,
) -> StudentImportPreview:
    preview, _ = await validate_student_import(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=_workspace_id(principal),
        rows=payload.rows,
    )
    return preview


@router.post("/commit", response_model=StudentImportCommitResponse)
async def commit_students_import(
    payload: StudentImportPayload,
    principal: EducationManagePrincipal,
    session: DB,
) -> StudentImportCommitResponse:
    try:
        preview, result = await commit_student_import(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=_workspace_id(principal),
            rows=payload.rows,
        )
        if result is None:
            await session.rollback()
            return StudentImportCommitResponse(committed=False, preview=preview)
        await session.commit()
        return StudentImportCommitResponse(committed=True, preview=preview, result=result)
    except StudentImportConflictError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
