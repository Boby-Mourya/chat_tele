"""Section 23: only enabled, unsuspended Workspace administrators count as active."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException

from northstar_api.models import Workspace, WorkspaceRole, WorkspaceStatus
from northstar_api.modules.workspace.services.member_service import (
    ensure_member_status_change_allowed,
)


class _AdministratorSession:
    def __init__(self, enabled_administrators):
        self.enabled_administrators = enabled_administrators
        self.queries: list[str] = []

    async def scalars(self, statement):
        sql = str(statement).lower()
        self.queries.append(sql)
        # This fixture represents the actual database result after the query
        # filters disabled users. Fail rather than silently faking that filter.
        assert "join users on users.id = workspace_memberships.user_id" in sql
        assert "users.is_active is true" in sql
        assert "workspace_memberships.tenant_id" in sql
        assert "workspace_memberships.workspace_id" in sql
        return self.enabled_administrators


def _workspace(owner_id, *, suspended=()):
    return Workspace(
        id=uuid4(),
        tenant_id=uuid4(),
        name="Admissions",
        slug="admissions",
        status=WorkspaceStatus.ACTIVE,
        created_by=owner_id,
        settings_json={
            "workspaceMemberStatusV1": {str(user_id): "suspended" for user_id in suspended},
            "unrelatedSetting": {"preserved": True},
        },
        branding_json={},
    )


@pytest.mark.asyncio
async def test_disabled_administrator_cannot_allow_only_enabled_admin_to_be_suspended():
    owner_id = uuid4()
    target_id = uuid4()
    disabled_admin_id = uuid4()
    workspace = _workspace(owner_id)
    # The disabled administrator is intentionally absent from query results.
    session = _AdministratorSession([target_id])
    snapshot = workspace.settings_json.copy()

    with pytest.raises(HTTPException) as error:
        await ensure_member_status_change_allowed(
            session, workspace, target_id, WorkspaceRole.ADMIN, "suspended"
        )

    assert error.value.status_code == 409
    assert "at least one active administrator" in error.value.detail
    assert len(session.queries) == 1
    assert disabled_admin_id != target_id
    assert workspace.settings_json == snapshot


@pytest.mark.asyncio
async def test_enabled_unsuspended_administrator_allows_other_admin_suspension():
    owner_id = uuid4()
    target_id = uuid4()
    other_enabled_admin_id = uuid4()
    workspace = _workspace(owner_id)
    session = _AdministratorSession([target_id, other_enabled_admin_id])

    await ensure_member_status_change_allowed(
        session, workspace, target_id, WorkspaceRole.ADMIN, "suspended"
    )

    assert len(session.queries) == 1


@pytest.mark.asyncio
async def test_enabled_but_suspended_administrator_is_not_a_valid_remaining_admin():
    owner_id = uuid4()
    target_id = uuid4()
    other_suspended_admin_id = uuid4()
    workspace = _workspace(owner_id, suspended=(other_suspended_admin_id,))
    session = _AdministratorSession([target_id, other_suspended_admin_id])

    with pytest.raises(HTTPException) as error:
        await ensure_member_status_change_allowed(
            session, workspace, target_id, WorkspaceRole.ADMIN, "suspended"
        )

    assert error.value.status_code == 409
    assert len(session.queries) == 1
