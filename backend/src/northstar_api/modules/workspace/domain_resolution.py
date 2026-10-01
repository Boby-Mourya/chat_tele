from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import set_tenant_context
from northstar_api.models import Workspace, WorkspaceStatus

from .store import settings_document


def normalize_hostname(value: str) -> str:
    normalized = value.strip().lower().rstrip(".")
    if (
        not normalized
        or len(normalized) > 253
        or "://" in normalized
        or "/" in normalized
        or " " in normalized
    ):
        raise ValueError("Invalid hostname")
    return normalized


async def resolve_workspace_domain(session: AsyncSession, hostname: str) -> Workspace | None:
    """Resolve only an active, server-verified workspace custom domain.

    PostgreSQL uses the SECURITY DEFINER resolver created by the workspace-domain
    migration so pre-auth requests remain compatible with tenant RLS. SQLite is
    retained for tests/development and scans active workspaces in-process.
    """
    normalized = normalize_hostname(hostname)
    if session.bind and session.bind.dialect.name == "postgresql":
        row = (
            await session.execute(
                text(
                    "SELECT tenant_id, workspace_id "
                    "FROM northstar_resolve_workspace_domain(:hostname)"
                ),
                {"hostname": normalized},
            )
        ).mappings().first()
        if row is None:
            return None
        tenant_id = UUID(str(row["tenant_id"]))
        workspace_id = UUID(str(row["workspace_id"]))
        await set_tenant_context(session, tenant_id)
        return await session.scalar(
            select(Workspace).where(
                Workspace.id == workspace_id,
                Workspace.tenant_id == tenant_id,
                Workspace.status == WorkspaceStatus.ACTIVE,
            )
        )

    workspaces = await session.scalars(
        select(Workspace).where(Workspace.status == WorkspaceStatus.ACTIVE)
    )
    for workspace in workspaces:
        document = settings_document(workspace)
        if any(
            domain.hostname == normalized and domain.status == "active"
            for domain in document.domains.domains
        ):
            return workspace
    return None
