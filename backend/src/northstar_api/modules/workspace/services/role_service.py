"""Workspace custom-role validation and lifecycle for the existing settings document.

Call after tenant/workspace authorization and the shared Workspace write lock.
The API handler still owns audit/outbox and the transaction. No new ORM mapping
or replacement role-storage format is introduced.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.models import Agent, Workspace, WorkspaceMembership
from northstar_api.modules.workspace.contracts import RolesSettings, TeamsSettings
from northstar_api.modules.workspace.store import save_document, settings_document
from northstar_api.security import Principal


def _role_uuid(value: str, label: str) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid {label} identifier") from None


async def validate_workspace_role_assignments(
    payload: RolesSettings,
    principal: Principal,
    session: AsyncSession,
    workspace_id: UUID,
) -> None:
    """Reject duplicate IDs, privilege delegation and cross-workspace references.

    Keep the existing role API's query predicates and error messages. In
    particular, member/agent IDs are scoped to BOTH tenant and Workspace.
    """
    role_ids = [role.id for role in payload.custom_roles]
    if len(role_ids) != len(set(role_ids)):
        raise HTTPException(status_code=422, detail="Custom role identifiers must be unique")
    known_roles = set(role_ids)
    for role in payload.custom_roles:
        if not set(role.permissions) <= set(principal.permissions):
            raise HTTPException(
                status_code=403,
                detail=f"Cannot delegate permissions not held by the current administrator ({role.name})",
            )

    requested_users = {_role_uuid(user_id, "member") for user_id in payload.member_role_ids}
    if requested_users:
        workspace_members = set(
            await session.scalars(
                select(WorkspaceMembership.user_id).where(
                    WorkspaceMembership.tenant_id == principal.tenant_id,
                    WorkspaceMembership.workspace_id == workspace_id,
                )
            )
        )
        if not requested_users <= workspace_members:
            raise HTTPException(
                status_code=422,
                detail="A custom role assignment references a member outside this workspace",
            )
    for assigned in payload.member_role_ids.values():
        if not set(assigned) <= known_roles:
            raise HTTPException(
                status_code=422,
                detail="A custom role assignment references an unknown role",
            )

    agent_ids: set[UUID] = set()
    for role in payload.custom_roles:
        for value in role.resources.selected.get("agents", []):
            agent_ids.add(_role_uuid(value, "agent resource"))
    if agent_ids:
        workspace_agents = set(
            await session.scalars(
                select(Agent.id).where(
                    Agent.tenant_id == principal.tenant_id,
                    Agent.workspace_id == workspace_id,
                    Agent.deleted_at.is_(None),
                )
            )
        )
        if not agent_ids <= workspace_agents:
            raise HTTPException(
                status_code=422,
                detail="A custom role references an agent outside this workspace",
            )


def ensure_role_removal_safe(
    current_roles: RolesSettings,
    requested_roles: RolesSettings,
    current_teams: TeamsSettings,
) -> None:
    """Prevent removal of a role that is still assigned to an existing team.

    Only *removed* role IDs are checked: historical unrelated team references
    must not block an otherwise compatible role update.
    """
    removed_ids = (
        {role.id for role in current_roles.custom_roles}
        - {role.id for role in requested_roles.custom_roles}
    )
    if not removed_ids:
        return
    for team in current_teams.teams:
        if removed_ids.intersection(team.role_ids):
            raise HTTPException(
                status_code=409,
                detail=f"Remove the role assignment from team {team.name} before deleting its role",
            )


def update_workspace_roles(workspace: Workspace, payload: RolesSettings) -> dict[str, Any]:
    """Persist role settings using the established JSON compatibility path."""
    document = settings_document(workspace)
    ensure_role_removal_safe(document.roles, payload, document.teams)
    before = document.roles.model_dump(by_alias=True, mode="json")
    document.roles = payload
    save_document(workspace, document)
    return before
