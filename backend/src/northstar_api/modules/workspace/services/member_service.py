"""Workspace member lifecycle policy, independent of HTTP route registration.

Call these guards only after the existing tenant-scoped membership loader and
workspace write lock. The caller owns the transaction, audit and outbox.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.models import User, Workspace, WorkspaceMembership, WorkspaceRole
from northstar_api.modules.workspace.member_state import is_member_suspended, member_statuses


async def ensure_member_status_change_allowed(
    session: AsyncSession,
    workspace: Workspace,
    member_user_id: UUID,
    member_role: WorkspaceRole,
    status: Literal["active", "suspended"],
) -> None:
    """Preserve an active owner and at least one usable Workspace administrator.

    The Workspace row must already be locked by the caller; read the current
    membership roles, account state and freshly reloaded status document together.
    A disabled user account cannot serve as the remaining active administrator.
    """
    if status != "suspended":
        return

    # The existing transfer-ownership endpoint points `created_by` at the
    # new owner. Do not leave that owner suspended while another admin exists:
    # transferring ownership first keeps the lifecycle internally consistent.
    if workspace.created_by == member_user_id:
        raise HTTPException(
            status_code=409,
            detail="Transfer workspace ownership before suspending the current owner",
        )

    if member_role != WorkspaceRole.ADMIN:
        return

    administrator_ids = await session.scalars(
        select(WorkspaceMembership.user_id)
        .join(User, User.id == WorkspaceMembership.user_id)
        .where(
            WorkspaceMembership.tenant_id == workspace.tenant_id,
            WorkspaceMembership.workspace_id == workspace.id,
            WorkspaceMembership.role == WorkspaceRole.ADMIN,
            User.is_active.is_(True),
        )
    )
    statuses = member_statuses(workspace.settings_json)
    active_administrator_ids = {
        user_id for user_id in administrator_ids if statuses.get(str(user_id)) != "suspended"
    }
    if member_user_id in active_administrator_ids and len(active_administrator_ids) <= 1:
        raise HTTPException(
            status_code=409,
            detail="The workspace must keep at least one active administrator",
        )


def ensure_ownership_transfer_allowed(
    workspace: Workspace,
    member_user_id: UUID,
    *,
    account_is_active: bool = True,
) -> None:
    """A suspended Workspace member or disabled account cannot become owner.

    Preserve the established two-argument service contract. HTTP callers pass
    the current User.is_active value retrieved by the scoped member loader.
    """
    if not account_is_active:
        raise HTTPException(
            status_code=409,
            detail="Reactivate the user account before transferring workspace ownership",
        )
    if is_member_suspended(workspace.settings_json, member_user_id):
        raise HTTPException(
            status_code=409,
            detail="Reactivate the member before transferring ownership",
        )
