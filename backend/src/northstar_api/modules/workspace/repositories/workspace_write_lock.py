"""Serialize writes to the existing Workspace settings and branding JSON.

The scoped Workspace loader checks tenant membership and active status before
calling this helper. PostgreSQL SELECT FOR UPDATE then reloads the latest row
before any handler parses or modifies the shared document. Keep the existing
JSON layout and compatibility paths; this helper introduces no new tables.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.models import Workspace, WorkspaceStatus


async def lock_workspace_settings(session: AsyncSession, workspace: Workspace) -> None:
    """Lock/reload an already-authorized workspace for its current transaction.

    Call before parsing settings_document or changing branding_json. Reload
    created_by with the JSON and status so ownership checks also see transfers
    committed while the caller was waiting for the lock. The row lock is
    released by the caller's existing commit/rollback. A workspace archived
    between authorization and lock acquisition must not be updated.
    """
    await session.refresh(
        workspace,
        attribute_names=["settings_json", "branding_json", "status", "created_by"],
        with_for_update=True,
    )
    if workspace.status != WorkspaceStatus.ACTIVE:
        raise HTTPException(status_code=404, detail="Workspace not found")
