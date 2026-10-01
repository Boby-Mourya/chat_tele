from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from northstar_api.dependencies import DBSession, require_permissions
from northstar_api.models import Agent, WorkspaceMembership
from northstar_api.modules.branding.repositories import persist_branding_document
from northstar_api.security import Principal

from .contracts import DashboardSettings, RolesSettings, TeamsSettings
from .repositories.workspace_write_lock import lock_workspace_settings
from .security_policy import validate_business_timezone
from .services.dashboard_service import update_workspace_dashboard
from .services.role_service import update_workspace_roles, validate_workspace_role_assignments
from .services.team_service import sync_workspace_team_records, update_workspace_teams
from .store import load_workspace, record_workspace_change, settings_document

router = APIRouter()
RolesManagePrincipal = Annotated[Principal, Depends(require_permissions("roles.manage"))]
TeamsManagePrincipal = Annotated[Principal, Depends(require_permissions("teams.manage"))]
BrandEditPrincipal = Annotated[Principal, Depends(require_permissions("branding.edit"))]


def _uuid(value: str, label: str) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid {label} identifier") from None


async def _workspace_member_ids(session: DBSession, principal: Principal, workspace_id: UUID) -> set[UUID]:
    return set(
        await session.scalars(
            select(WorkspaceMembership.user_id).where(
                WorkspaceMembership.tenant_id == principal.tenant_id,
                WorkspaceMembership.workspace_id == workspace_id,
            )
        )
    )


async def _workspace_agent_ids(session: DBSession, principal: Principal, workspace_id: UUID) -> set[UUID]:
    return set(
        await session.scalars(
            select(Agent.id).where(
                Agent.tenant_id == principal.tenant_id,
                Agent.workspace_id == workspace_id,
                Agent.deleted_at.is_(None),
            )
        )
    )


async def _validate_roles(
    payload: RolesSettings,
    principal: Principal,
    session: DBSession,
    workspace_id: UUID,
) -> None:
    """Compatibility entry point; the feature-owned service enforces role policy."""
    await validate_workspace_role_assignments(payload, principal, session, workspace_id)


async def _validate_teams(
    payload: TeamsSettings,
    principal: Principal,
    session: DBSession,
    workspace_id: UUID,
    roles: RolesSettings,
) -> None:
    ids = [team.id for team in payload.teams]
    names = [team.name.casefold() for team in payload.teams]
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=422, detail="Team identifiers must be unique")
    if len(names) != len(set(names)):
        raise HTTPException(status_code=422, detail="Team names must be unique in a workspace")

    # Apply the same timezone validation already used by Workspace General.
    # Reject invalid team schedules before querying membership or persisting
    # the shared settings document; the legacy JSON representation is unchanged.
    for team in payload.teams:
        validate_business_timezone(team.business_hours.timezone)

    workspace_members = await _workspace_member_ids(session, principal, workspace_id)
    workspace_agents = await _workspace_agent_ids(session, principal, workspace_id)
    custom_roles = {role.id for role in roles.custom_roles}
    for team in payload.teams:
        members = {_uuid(value, "team member") for value in team.member_ids}
        managers = {_uuid(value, "team manager") for value in team.manager_ids}
        agents = {_uuid(value, "team agent") for value in team.agent_ids}
        if not members <= workspace_members or not managers <= workspace_members:
            raise HTTPException(
                status_code=422,
                detail=f"Team {team.name} references a member outside this workspace",
            )
        if not managers <= members:
            raise HTTPException(
                status_code=422,
                detail=f"Team {team.name} managers must also be team members",
            )
        if not agents <= workspace_agents:
            raise HTTPException(
                status_code=422,
                detail=f"Team {team.name} references an agent outside this workspace",
            )
        if not set(team.role_ids) <= custom_roles:
            raise HTTPException(
                status_code=422,
                detail=f"Team {team.name} references an unknown custom role",
            )


@router.patch("/roles", response_model=RolesSettings)
async def update_roles(
    payload: RolesSettings,
    request: Request,
    principal: RolesManagePrincipal,
    session: DBSession,
) -> RolesSettings:
    _, workspace = await load_workspace(principal, session)
    await lock_workspace_settings(session, workspace)
    await _validate_roles(payload, principal, session, workspace.id)
    before = update_workspace_roles(workspace, payload)
    record_workspace_change(
        session,
        principal,
        workspace,
        "workspace.role.updated",
        [role.id for role in payload.custom_roles],
        resource_type="workspace_roles",
        resource_id=str(workspace.id),
        before=before,
        after=payload.model_dump(by_alias=True, mode="json"),
        request=request,
    )
    await session.commit()
    return payload


@router.patch("/teams", response_model=TeamsSettings)
async def update_teams(
    payload: TeamsSettings,
    request: Request,
    principal: TeamsManagePrincipal,
    session: DBSession,
) -> TeamsSettings:
    _, workspace = await load_workspace(principal, session)
    await lock_workspace_settings(session, workspace)
    document = settings_document(workspace)
    await _validate_teams(payload, principal, session, workspace.id, document.roles)
    before = update_workspace_teams(workspace, payload)
    await sync_workspace_team_records(session, workspace, payload)
    record_workspace_change(
        session,
        principal,
        workspace,
        "workspace.teams.updated",
        [team.id for team in payload.teams],
        resource_type="workspace_teams",
        resource_id=str(workspace.id),
        before=before,
        after=payload.model_dump(by_alias=True, mode="json"),
        request=request,
    )
    await session.commit()
    return payload


@router.patch("/dashboard", response_model=DashboardSettings)
async def update_dashboard(
    payload: DashboardSettings,
    request: Request,
    principal: BrandEditPrincipal,
    session: DBSession,
) -> DashboardSettings:
    _, workspace = await load_workspace(principal, session)
    await lock_workspace_settings(session, workspace)
    before = update_workspace_dashboard(workspace, payload)
    await persist_branding_document(session, workspace, settings_document(workspace))
    record_workspace_change(
        session,
        principal,
        workspace,
        "workspace.dashboard.updated",
        [widget.id for widget in payload.widgets],
        resource_type="workspace_dashboard_layout",
        resource_id=str(workspace.id),
        before=before,
        after=payload.model_dump(by_alias=True, mode="json"),
        request=request,
    )
    await session.commit()
    return payload
