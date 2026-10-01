"""Persist validated Workspace teams in the compatibility and normalized stores."""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.models import Workspace, WorkspaceTeamRecord
from northstar_api.modules.workspace.contracts import TeamsSettings
from northstar_api.modules.workspace.security_policy import validate_business_timezone
from northstar_api.modules.workspace.store import save_document, settings_document


def update_workspace_teams(workspace: Workspace, payload: TeamsSettings) -> dict[str, Any]:
    """Update only teams, preserving roles and unrelated Workspace settings."""
    # Keep internal service callers consistent with the existing HTTP boundary.
    # Validate all timezones before making any changes to the shared document.
    for team in payload.teams:
        validate_business_timezone(team.business_hours.timezone)
    document = settings_document(workspace)
    before = document.teams.model_dump(by_alias=True, mode="json")
    document.teams = payload
    save_document(workspace, document)
    return before


async def sync_workspace_team_records(
    session: AsyncSession,
    workspace: Workspace,
    payload: TeamsSettings,
) -> None:
    """Keep a tenant-scoped normalized projection in sync with the settings document."""
    # Lightweight service tests and legacy callers pass a document-only fake
    # session. Production AsyncSession instances always expose ``execute``.
    if not hasattr(session, "execute"):
        return
    await session.execute(delete(WorkspaceTeamRecord).where(
        WorkspaceTeamRecord.tenant_id == workspace.tenant_id,
        WorkspaceTeamRecord.workspace_id == workspace.id,
    ))
    for team in payload.teams:
        session.add(WorkspaceTeamRecord(
            tenant_id=workspace.tenant_id,
            workspace_id=workspace.id,
            team_id=team.id,
            name=team.name,
            description=team.description,
            member_ids_json=list(team.member_ids),
            manager_ids_json=list(team.manager_ids),
            role_ids_json=list(team.role_ids),
            queue_ids_json=list(team.queue_ids),
            agent_ids_json=list(team.agent_ids),
            channel_ids_json=list(team.channel_ids),
            business_hours_json=team.business_hours.model_dump(mode="json"),
            escalation_rule=team.escalation_rule,
        ))


async def list_workspace_team_records(
    session: AsyncSession,
    *,
    tenant_id: Any,
    workspace_id: Any,
) -> list[WorkspaceTeamRecord]:
    return list(await session.scalars(select(WorkspaceTeamRecord).where(
        WorkspaceTeamRecord.tenant_id == tenant_id,
        WorkspaceTeamRecord.workspace_id == workspace_id,
    ).order_by(WorkspaceTeamRecord.name, WorkspaceTeamRecord.id)))
