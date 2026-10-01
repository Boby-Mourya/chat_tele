"""Section 23: an active Workspace owner must transfer ownership before suspension."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException

from northstar_api.models import Workspace, WorkspaceRole, WorkspaceStatus
from northstar_api.modules.workspace.services.member_service import (
    ensure_member_status_change_allowed,
)


class _Session:
    def __init__(self, administrators=()):
        self.administrators = administrators
        self.queries = 0

    async def scalars(self, _query):
        self.queries += 1
        return self.administrators


def _workspace(owner_id):
    return Workspace(
        id=uuid4(),
        tenant_id=uuid4(),
        name="Admissions",
        slug="admissions",
        status=WorkspaceStatus.ACTIVE,
        created_by=owner_id,
        settings_json={"workspaceMemberStatusV1": {}},
        branding_json={},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [WorkspaceRole.ADMIN, WorkspaceRole.MANAGER])
async def test_current_owner_cannot_be_suspended_even_with_another_admin(role):
    owner_id = uuid4()
    another_admin = uuid4()
    session = _Session([owner_id, another_admin])
    workspace = _workspace(owner_id)

    with pytest.raises(HTTPException) as error:
        await ensure_member_status_change_allowed(session, workspace, owner_id, role, "suspended")

    assert error.value.status_code == 409
    assert error.value.detail == "Transfer workspace ownership before suspending the current owner"
    assert session.queries == 0
    assert workspace.settings_json == {"workspaceMemberStatusV1": {}}


@pytest.mark.asyncio
async def test_other_administrator_remains_suspendable_if_owner_stays_active():
    owner_id = uuid4()
    administrator_id = uuid4()
    workspace = _workspace(owner_id)
    session = _Session([owner_id, administrator_id])

    await ensure_member_status_change_allowed(
        session, workspace, administrator_id, WorkspaceRole.ADMIN, "suspended"
    )

    assert session.queries == 1


@pytest.mark.asyncio
async def test_owner_reactivation_is_not_blocked_by_suspension_guard():
    owner_id = uuid4()
    workspace = _workspace(owner_id)
    workspace.settings_json = {"workspaceMemberStatusV1": {str(owner_id): "suspended"}}
    session = _Session()

    await ensure_member_status_change_allowed(session, workspace, owner_id, WorkspaceRole.ADMIN, "active")

    assert session.queries == 0
