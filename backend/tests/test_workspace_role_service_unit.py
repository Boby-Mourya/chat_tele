"""Section 23 custom-role lifecycle regression coverage."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from northstar_api.models import Workspace, WorkspaceStatus
from northstar_api.modules.workspace import access
from northstar_api.modules.workspace.contracts import (
    CustomRole,
    RolesSettings,
    TeamsSettings,
    WorkspaceSettingsBundle,
    WorkspaceTeam,
)
from northstar_api.modules.workspace.services.role_service import (
    ensure_role_removal_safe,
    update_workspace_roles,
)
from northstar_api.modules.workspace.store import settings_document


def _role() -> CustomRole:
    return CustomRole(name="Admissions", permissions=["workspace.view"])


def _workspace(document: WorkspaceSettingsBundle) -> Workspace:
    return Workspace(
        id=uuid4(),
        tenant_id=uuid4(),
        name="Admissions",
        slug="admissions",
        status=WorkspaceStatus.ACTIVE,
        settings_json={
            "workspaceSettingsV2": document.model_dump(by_alias=True, mode="json"),
            "unrelatedSetting": {"preserved": True},
        },
        branding_json={},
    )


def test_referenced_role_cannot_be_removed_and_document_is_unchanged() -> None:
    role = _role()
    document = WorkspaceSettingsBundle(
        roles=RolesSettings(custom_roles=[role]),
        teams=TeamsSettings(teams=[WorkspaceTeam(name="Admissions", role_ids=[role.id])]),
    )
    workspace = _workspace(document)
    before = workspace.settings_json.copy()

    with pytest.raises(HTTPException) as error:
        update_workspace_roles(workspace, RolesSettings())

    assert error.value.status_code == 409
    assert "Admissions" in error.value.detail
    assert workspace.settings_json == before


def test_role_update_preserves_team_and_unrelated_settings() -> None:
    role = _role()
    document = WorkspaceSettingsBundle(
        roles=RolesSettings(custom_roles=[role]),
        teams=TeamsSettings(teams=[WorkspaceTeam(name="Admissions", role_ids=[role.id])]),
    )
    document.general.industry = "Education"
    workspace = _workspace(document)
    renamed = role.model_copy(update={"name": "Admissions and support"})

    before = update_workspace_roles(workspace, RolesSettings(custom_roles=[renamed]))

    saved = settings_document(workspace)
    assert before["customRoles"][0]["name"] == "Admissions"
    assert saved.roles.custom_roles[0].name == "Admissions and support"
    assert saved.teams.teams[0].role_ids == [role.id]
    assert saved.general.industry == "Education"
    assert workspace.settings_json["unrelatedSetting"] == {"preserved": True}


def test_unreferenced_role_can_be_removed_without_rejecting_historical_team_reference() -> None:
    role = _role()
    historical_id = str(uuid4())
    current = RolesSettings(custom_roles=[role])
    teams = TeamsSettings(teams=[WorkspaceTeam(name="Legacy", role_ids=[historical_id])])

    ensure_role_removal_safe(current, RolesSettings(), teams)
    ensure_role_removal_safe(
        current,
        current,
        TeamsSettings(teams=[WorkspaceTeam(name="Current", role_ids=[role.id])]),
    )


class _Session:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


@pytest.mark.asyncio
async def test_roles_api_refuses_removal_before_audit_or_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    role = _role()
    document = WorkspaceSettingsBundle(
        roles=RolesSettings(custom_roles=[role]),
        teams=TeamsSettings(teams=[WorkspaceTeam(name="Admissions", role_ids=[role.id])]),
    )
    workspace = _workspace(document)
    session = _Session()
    effects: list[str] = []

    async def scoped_loader(_principal, _session):
        return None, workspace

    async def locked(_session, _workspace):
        assert _workspace is workspace
        effects.append("lock")

    async def valid_roles(_payload, _principal, _session, _workspace_id):
        effects.append("validate")

    monkeypatch.setattr(access, "load_workspace", scoped_loader)
    monkeypatch.setattr(access, "lock_workspace_settings", locked)
    monkeypatch.setattr(access, "_validate_roles", valid_roles)
    monkeypatch.setattr(access, "record_workspace_change", lambda *_args, **_kwargs: effects.append("audit"))

    with pytest.raises(HTTPException) as error:
        await access.update_roles(
            RolesSettings(),
            object(),  # type: ignore[arg-type]
            SimpleNamespace(),  # type: ignore[arg-type]
            session,  # type: ignore[arg-type]
        )

    assert error.value.status_code == 409
    assert effects == ["lock", "validate"]
    assert session.commits == 0
    assert settings_document(workspace).teams.teams[0].role_ids == [role.id]
