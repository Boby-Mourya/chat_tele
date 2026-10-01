"""Member status/ownership transitions serialize against shared Workspace writes."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from northstar_api.models import Workspace, WorkspaceRole, WorkspaceStatus
from northstar_api.modules.workspace import members
from northstar_api.modules.workspace.contracts import WorkspaceSettingsBundle


class _Session:
    def __init__(self, latest: dict[str, object], *, latest_owner=None):
        self.latest = latest
        self.latest_owner = latest_owner
        self.refreshes: list[tuple[str, ...]] = []
        self.commits = 0

    async def refresh(self, workspace, *, attribute_names, with_for_update):
        assert with_for_update is True
        self.refreshes.append(tuple(attribute_names))
        workspace.settings_json = self.latest
        workspace.status = WorkspaceStatus.ACTIVE
        if self.latest_owner is not None:
            workspace.created_by = self.latest_owner

    async def commit(self):
        self.commits += 1


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


def _mock_membership(
    monkeypatch: pytest.MonkeyPatch,
    workspace: Workspace,
    *,
    role: WorkspaceRole,
    account_is_active: bool = True,
):
    user_id = uuid4()
    membership = SimpleNamespace(role=role)
    user = SimpleNamespace(
        id=user_id, is_active=account_is_active, mfa_enabled=False, last_login_at=None
    )

    async def scoped_loader(_principal, _session):
        return None, workspace

    async def require_member(_session, _workspace, _user_id):
        assert _workspace is workspace
        assert _user_id == user_id
        return membership, user

    monkeypatch.setattr(members, "load_workspace", scoped_loader)
    monkeypatch.setattr(members, "_require_member", require_member)
    monkeypatch.setattr(members, "record_workspace_change", lambda *_args, **_kwargs: None)
    return user_id, membership


@pytest.mark.asyncio
async def test_suspend_preserves_other_users_and_concurrent_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace()
    other_user = uuid4()
    latest = {
        "workspaceSettingsV2": WorkspaceSettingsBundle().model_dump(by_alias=True, mode="json"),
        "workspaceMemberStatusV1": {str(other_user): "suspended"},
        "otherSetting": {"preserve": True},
    }
    session = _Session(latest)
    target_id, _ = _mock_membership(monkeypatch, workspace, role=WorkspaceRole.MANAGER)
    principal = SimpleNamespace(user_id=uuid4())

    result = await members.suspend_member(
        target_id,
        principal,  # type: ignore[arg-type]
        session,  # type: ignore[arg-type]
    )

    assert result.status == "suspended"
    assert workspace.settings_json["workspaceMemberStatusV1"] == {
        str(other_user): "suspended",
        str(target_id): "suspended",
    }
    assert workspace.settings_json["otherSetting"] == {"preserve": True}
    assert "workspaceSettingsV2" in workspace.settings_json
    assert session.refreshes == [("settings_json", "branding_json", "status", "created_by")]
    assert session.commits == 1


@pytest.mark.asyncio
async def test_ownership_transfer_refuses_newly_suspended_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace()
    target_id, membership = _mock_membership(monkeypatch, workspace, role=WorkspaceRole.VIEWER)
    session = _Session({"workspaceMemberStatusV1": {str(target_id): "suspended"}})
    principal = SimpleNamespace(workspace_role=WorkspaceRole.ADMIN)

    with pytest.raises(HTTPException) as error:
        await members.transfer_ownership(
            target_id,
            principal,  # type: ignore[arg-type]
            session,  # type: ignore[arg-type]
        )

    assert error.value.status_code == 409
    assert membership.role == WorkspaceRole.VIEWER
    assert workspace.created_by != target_id
    assert session.refreshes == [("settings_json", "branding_json", "status", "created_by")]
    assert session.commits == 0


@pytest.mark.asyncio
async def test_suspension_refuses_owner_transferred_during_scoped_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace()
    former_owner = uuid4()
    workspace.created_by = former_owner
    target_id, _ = _mock_membership(monkeypatch, workspace, role=WorkspaceRole.MANAGER)
    session = _Session({"workspaceMemberStatusV1": {}}, latest_owner=target_id)
    principal = SimpleNamespace(user_id=former_owner)

    with pytest.raises(HTTPException) as error:
        await members.suspend_member(
            target_id,
            principal,  # type: ignore[arg-type]
            session,  # type: ignore[arg-type]
        )

    assert error.value.status_code == 409
    assert "Transfer workspace ownership" in error.value.detail
    assert workspace.created_by == target_id
    assert workspace.settings_json["workspaceMemberStatusV1"] == {}
    assert session.refreshes == [("settings_json", "branding_json", "status", "created_by")]
    assert session.commits == 0


@pytest.mark.asyncio
async def test_ownership_transfer_refuses_disabled_user_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace()
    current_owner_id = uuid4()
    workspace.created_by = current_owner_id
    target_id, membership = _mock_membership(
        monkeypatch,
        workspace,
        role=WorkspaceRole.VIEWER,
        account_is_active=False,
    )
    session = _Session({"workspaceMemberStatusV1": {}})
    principal = SimpleNamespace(workspace_role=WorkspaceRole.ADMIN)

    with pytest.raises(HTTPException) as error:
        await members.transfer_ownership(
            target_id,
            principal,  # type: ignore[arg-type]
            session,  # type: ignore[arg-type]
        )

    assert error.value.status_code == 409
    assert error.value.detail == "Reactivate the user account before transferring workspace ownership"
    assert membership.role == WorkspaceRole.VIEWER
    assert workspace.created_by == current_owner_id
    assert session.refreshes == [("settings_json", "branding_json", "status", "created_by")]
    assert session.commits == 0
