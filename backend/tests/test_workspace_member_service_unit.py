"""Section 23 service contract: current scoped member status and ownership checks."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException

from northstar_api.models import Workspace, WorkspaceRole, WorkspaceStatus
from northstar_api.modules.workspace.services.member_service import (
    ensure_member_status_change_allowed,
    ensure_ownership_transfer_allowed,
)


class _Session:
    def __init__(self, administrator_ids):
        self.administrator_ids = administrator_ids
        self.queries = 0

    async def scalars(self, _query):
        self.queries += 1
        return self.administrator_ids


def _workspace(statuses=None):
    return Workspace(
        id=uuid4(),
        tenant_id=uuid4(),
        name="Admissions",
        slug="admissions",
        status=WorkspaceStatus.ACTIVE,
        settings_json={"workspaceMemberStatusV1": statuses or {}},
        branding_json={},
    )


@pytest.mark.asyncio
async def test_last_active_administrator_cannot_be_suspended():
    administrator_id = uuid4()
    workspace = _workspace()
    session = _Session([administrator_id])

    with pytest.raises(HTTPException) as error:
        await ensure_member_status_change_allowed(
            session, workspace, administrator_id, WorkspaceRole.ADMIN, "suspended"
        )

    assert error.value.status_code == 409
    assert error.value.detail == "The workspace must keep at least one active administrator"
    assert session.queries == 1


@pytest.mark.asyncio
async def test_other_active_administrator_preserves_ability_to_suspend():
    administrator_id = uuid4()
    other_administrator_id = uuid4()
    workspace = _workspace({str(other_administrator_id): "suspended"})
    session = _Session([administrator_id, other_administrator_id])

    with pytest.raises(HTTPException):
        await ensure_member_status_change_allowed(
            session, workspace, administrator_id, WorkspaceRole.ADMIN, "suspended"
        )

    workspace.settings_json = {"workspaceMemberStatusV1": {}}
    await ensure_member_status_change_allowed(
        session, workspace, administrator_id, WorkspaceRole.ADMIN, "suspended"
    )
    assert session.queries == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role,status",
    [
        (WorkspaceRole.MANAGER, "suspended"),
        (WorkspaceRole.ADMIN, "active"),
        (WorkspaceRole.VIEWER, "active"),
    ],
)
async def test_non_admin_suspension_and_reactivation_need_no_admin_query(role, status):
    session = _Session([])
    await ensure_member_status_change_allowed(session, _workspace(), uuid4(), role, status)
    assert session.queries == 0


@pytest.mark.asyncio
async def test_already_suspended_administrator_does_not_remove_the_last_active_one():
    suspended_administrator_id = uuid4()
    active_administrator_id = uuid4()
    workspace = _workspace({str(suspended_administrator_id): "suspended"})
    session = _Session([suspended_administrator_id, active_administrator_id])

    await ensure_member_status_change_allowed(
        session, workspace, suspended_administrator_id, WorkspaceRole.ADMIN, "suspended"
    )
    assert session.queries == 1


def test_ownership_target_must_be_active():
    member_user_id = uuid4()
    workspace = _workspace({str(member_user_id): "suspended"})

    with pytest.raises(HTTPException) as error:
        ensure_ownership_transfer_allowed(workspace, member_user_id)
    assert error.value.status_code == 409
    assert error.value.detail == "Reactivate the member before transferring ownership"

    workspace.settings_json = {"workspaceMemberStatusV1": {}}
    ensure_ownership_transfer_allowed(workspace, member_user_id)
