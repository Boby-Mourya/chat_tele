"""Section 23 ownership policy: user-account state and member status are distinct."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException

from northstar_api.models import Workspace, WorkspaceStatus
from northstar_api.modules.workspace.services.member_service import ensure_ownership_transfer_allowed


def _workspace() -> Workspace:
    return Workspace(
        id=uuid4(),
        tenant_id=uuid4(),
        name="Admissions",
        slug="admissions",
        status=WorkspaceStatus.ACTIVE,
        settings_json={"workspaceMemberStatusV1": {}},
        branding_json={},
    )


def test_inactive_user_account_cannot_receive_workspace_ownership() -> None:
    workspace = _workspace()
    candidate = uuid4()
    with pytest.raises(HTTPException) as error:
        ensure_ownership_transfer_allowed(workspace, candidate, account_is_active=False)
    assert error.value.status_code == 409
    assert "Reactivate the user account" in error.value.detail


def test_active_account_still_respects_workspace_suspension() -> None:
    workspace = _workspace()
    candidate = uuid4()
    workspace.settings_json = {"workspaceMemberStatusV1": {str(candidate): "suspended"}}
    with pytest.raises(HTTPException) as error:
        ensure_ownership_transfer_allowed(workspace, candidate, account_is_active=True)
    assert error.value.status_code == 409
    assert error.value.detail == "Reactivate the member before transferring ownership"


def test_active_account_preserves_original_two_argument_service_contract() -> None:
    workspace = _workspace()
    candidate = uuid4()
    ensure_ownership_transfer_allowed(workspace, candidate)
    ensure_ownership_transfer_allowed(workspace, candidate, account_is_active=True)
