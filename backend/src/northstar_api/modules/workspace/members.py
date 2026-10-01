from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy import select

from northstar_api.dependencies import DBSession, require_permissions
from northstar_api.models import User, WorkspaceMembership, WorkspaceRole
from northstar_api.onboarding_contract import SetupContract
from northstar_api.security import Principal

from .repositories.workspace_write_lock import lock_workspace_settings
from .services.member_service import (
    ensure_member_status_change_allowed,
    ensure_ownership_transfer_allowed,
)
from .store import load_workspace, record_workspace_change

router = APIRouter()
MemberViewPrincipal = Annotated[Principal, Depends(require_permissions("members.view"))]
MemberManagePrincipal = Annotated[Principal, Depends(require_permissions("members.manage"))]

_STATUS_KEY = "workspaceMemberStatusV1"


class MemberLifecycleOut(SetupContract):
    user_id: str
    status: Literal["active", "suspended"]
    mfa_enabled: bool
    last_active: str | None = None
    team_ids: list[str] = Field(default_factory=list)


def member_statuses(workspace_settings: dict[str, object] | None) -> dict[str, str]:
    raw = dict(workspace_settings or {}).get(_STATUS_KEY, {})
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items() if value in {"active", "suspended"}}


def is_member_suspended(workspace_settings: dict[str, object] | None, user_id: UUID) -> bool:
    return member_statuses(workspace_settings).get(str(user_id)) == "suspended"


def _save_status(workspace, user_id: UUID, status: Literal["active", "suspended"]) -> None:
    settings = dict(workspace.settings_json or {})
    statuses = member_statuses(settings)
    if status == "active":
        statuses.pop(str(user_id), None)
    else:
        statuses[str(user_id)] = status
    settings[_STATUS_KEY] = statuses
    workspace.settings_json = settings


def _team_ids(workspace_settings: dict[str, object] | None, user_id: UUID) -> list[str]:
    v2 = dict(workspace_settings or {}).get("workspaceSettingsV2", {})
    if not isinstance(v2, dict):
        return []
    teams = dict(v2.get("teams", {})).get("teams", []) if isinstance(v2.get("teams", {}), dict) else []
    result: list[str] = []
    for team in teams if isinstance(teams, list) else []:
        if not isinstance(team, dict):
            continue
        members = team.get("memberIds", [])
        if isinstance(members, list) and str(user_id) in {str(value) for value in members}:
            result.append(str(team.get("id", "")))
    return [value for value in result if value]


async def _require_member(session: DBSession, workspace, user_id: UUID) -> tuple[WorkspaceMembership, User]:
    row = (
        await session.execute(
            select(WorkspaceMembership, User)
            .join(User, User.id == WorkspaceMembership.user_id)
            .where(
                WorkspaceMembership.tenant_id == workspace.tenant_id,
                WorkspaceMembership.workspace_id == workspace.id,
                WorkspaceMembership.user_id == user_id,
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Workspace member not found")
    return row


@router.get("/members/lifecycle", response_model=list[MemberLifecycleOut])
async def get_member_lifecycle(
    principal: MemberViewPrincipal,
    session: DBSession,
) -> list[MemberLifecycleOut]:
    _, workspace = await load_workspace(principal, session)
    rows = (
        await session.execute(
            select(WorkspaceMembership, User)
            .join(User, User.id == WorkspaceMembership.user_id)
            .where(
                WorkspaceMembership.tenant_id == workspace.tenant_id,
                WorkspaceMembership.workspace_id == workspace.id,
            )
            .order_by(WorkspaceMembership.created_at, User.email)
        )
    ).all()
    statuses = member_statuses(workspace.settings_json)
    return [
        MemberLifecycleOut(
            user_id=str(user.id),
            status="suspended" if statuses.get(str(user.id)) == "suspended" else "active",
            mfa_enabled=user.mfa_enabled,
            last_active=user.last_login_at.isoformat() if user.last_login_at else None,
            team_ids=_team_ids(workspace.settings_json, user.id),
        )
        for _, user in rows
    ]


async def _set_member_status(
    member_user_id: UUID,
    status: Literal["active", "suspended"],
    principal: Principal,
    session: DBSession,
) -> MemberLifecycleOut:
    if member_user_id == principal.user_id:
        raise HTTPException(status_code=409, detail="Use another workspace administrator to change your own status")
    _, workspace = await load_workspace(principal, session)
    # A concurrent role/status change must be visible before checking the
    # last-active-admin invariant or writing workspaceMemberStatusV1.
    await lock_workspace_settings(session, workspace)
    membership, user = await _require_member(session, workspace, member_user_id)
    await ensure_member_status_change_allowed(
        session, workspace, member_user_id, membership.role, status
    )
    _save_status(workspace, member_user_id, status)
    record_workspace_change(
        session,
        principal,
        workspace,
        f"workspace.member.{status}",
        [str(member_user_id)],
    )
    await session.commit()
    return MemberLifecycleOut(
        user_id=str(user.id),
        status=status,
        mfa_enabled=user.mfa_enabled,
        last_active=user.last_login_at.isoformat() if user.last_login_at else None,
        team_ids=_team_ids(workspace.settings_json, user.id),
    )


@router.post("/members/{member_user_id}/suspend", response_model=MemberLifecycleOut)
async def suspend_member(
    member_user_id: UUID,
    principal: MemberManagePrincipal,
    session: DBSession,
) -> MemberLifecycleOut:
    return await _set_member_status(member_user_id, "suspended", principal, session)


@router.post("/members/{member_user_id}/reactivate", response_model=MemberLifecycleOut)
async def reactivate_member(
    member_user_id: UUID,
    principal: MemberManagePrincipal,
    session: DBSession,
) -> MemberLifecycleOut:
    return await _set_member_status(member_user_id, "active", principal, session)


@router.post("/members/{member_user_id}/transfer-ownership", response_model=MemberLifecycleOut)
async def transfer_ownership(
    member_user_id: UUID,
    principal: MemberManagePrincipal,
    session: DBSession,
) -> MemberLifecycleOut:
    if principal.workspace_role != WorkspaceRole.ADMIN:
        raise HTTPException(status_code=403, detail="Workspace administrator permission required")
    _, workspace = await load_workspace(principal, session)
    await lock_workspace_settings(session, workspace)
    membership, user = await _require_member(session, workspace, member_user_id)
    ensure_ownership_transfer_allowed(
        workspace, member_user_id, account_is_active=user.is_active
    )
    membership.role = WorkspaceRole.ADMIN
    workspace.created_by = member_user_id
    record_workspace_change(
        session,
        principal,
        workspace,
        "workspace.ownership.transferred",
        [str(member_user_id)],
    )
    await session.commit()
    return MemberLifecycleOut(
        user_id=str(user.id),
        status="active",
        mfa_enabled=user.mfa_enabled,
        last_active=user.last_login_at.isoformat() if user.last_login_at else None,
        team_ids=_team_ids(workspace.settings_json, user.id),
    )
