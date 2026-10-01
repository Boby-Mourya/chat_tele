from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import EmailStr
from sqlalchemy import select

from northstar_api.dependencies import DBSession, require_permissions
from northstar_api.models import User, WorkspaceMembership, WorkspaceRole
from northstar_api.onboarding_contract import SetupContract
from northstar_api.security import Principal

from .store import load_workspace

router = APIRouter()
GeneralViewPrincipal = Annotated[Principal, Depends(require_permissions("settings.view"))]


class WorkspaceOwnerOut(SetupContract):
    id: str
    name: str
    email: EmailStr


class WorkspaceGeneralMetadata(SetupContract):
    workspace_id: str
    tenant_id: str
    organization: str
    status: str
    owner: WorkspaceOwnerOut | None = None


@router.get("/general/metadata", response_model=WorkspaceGeneralMetadata)
async def get_general_metadata(
    principal: GeneralViewPrincipal,
    session: DBSession,
) -> WorkspaceGeneralMetadata:
    tenant, workspace = await load_workspace(principal, session)
    owner: User | None = None
    if workspace.created_by is not None:
        owner = await session.scalar(
            select(User)
            .join(
                WorkspaceMembership,
                WorkspaceMembership.user_id == User.id,
            )
            .where(
                User.id == workspace.created_by,
                WorkspaceMembership.tenant_id == workspace.tenant_id,
                WorkspaceMembership.workspace_id == workspace.id,
            )
        )
    if owner is None:
        owner = await session.scalar(
            select(User)
            .join(WorkspaceMembership, WorkspaceMembership.user_id == User.id)
            .where(
                WorkspaceMembership.tenant_id == workspace.tenant_id,
                WorkspaceMembership.workspace_id == workspace.id,
                WorkspaceMembership.role == WorkspaceRole.ADMIN,
            )
            .order_by(WorkspaceMembership.created_at, User.id)
        )
    return WorkspaceGeneralMetadata(
        workspace_id=str(workspace.id),
        tenant_id=str(tenant.id),
        organization=tenant.name,
        status=workspace.status.value,
        owner=(
            WorkspaceOwnerOut(id=str(owner.id), name=owner.name, email=owner.email)
            if owner is not None
            else None
        ),
    )
