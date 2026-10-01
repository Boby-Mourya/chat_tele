"""Section 23 team persistence and existing endpoint contract regression tests."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from northstar_api.models import Workspace, WorkspaceStatus
from northstar_api.modules.workspace import access
from northstar_api.modules.workspace.contracts import (
    CustomRole,
    RolesSettings,
    TeamsSettings,
    WorkspaceSettingsBundle,
    WorkspaceTeam,
)
from northstar_api.modules.workspace.services.team_service import update_workspace_teams
from northstar_api.modules.workspace.store import settings_document


def _workspace(document: WorkspaceSettingsBundle) -> Workspace:
    return Workspace(
        id=uuid4(),
        tenant_id=uuid4(),
        name="Admissions",
        slug="admissions",
        status=WorkspaceStatus.ACTIVE,
        settings_json={
            "workspaceSettingsV2": document.model_dump(by_alias=True, mode="json"),
            "unrelatedSetting": "preserve",
        },
        branding_json={},
    )


def test_team_service_updates_only_teams_and_returns_before_snapshot() -> None:
    role = CustomRole(name="Education", permissions=["workspace.view"])
    document = WorkspaceSettingsBundle(
        roles=RolesSettings(custom_roles=[role]),
        teams=TeamsSettings(teams=[WorkspaceTeam(name="Admissions", role_ids=[role.id])]),
    )
    document.general.industry = "Education"
    workspace = _workspace(document)
    requested = TeamsSettings(teams=[WorkspaceTeam(name="Student support", role_ids=[role.id])])

    before = update_workspace_teams(workspace, requested)
    saved = settings_document(workspace)

    assert before["teams"][0]["name"] == "Admissions"
    assert saved.teams.teams[0].name == "Student support"
    assert saved.teams.teams[0].role_ids == [role.id]
    assert saved.roles.custom_roles[0].id == role.id
    assert saved.general.industry == "Education"
    assert workspace.settings_json["unrelatedSetting"] == "preserve"


class _Session:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


@pytest.mark.asyncio
async def test_team_endpoint_validates_locked_roles_and_keeps_original_audit_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initial = WorkspaceSettingsBundle()
    workspace = _workspace(initial)
    current_role = CustomRole(name="Education", permissions=["workspace.view"])
    latest = WorkspaceSettingsBundle(roles=RolesSettings(custom_roles=[current_role]))
    latest.general.industry = "Education"
    session = _Session()
    effects: list[str] = []
    requested = TeamsSettings(teams=[WorkspaceTeam(name="Student support", role_ids=[current_role.id])])

    async def scoped_loader(_principal, _session):
        return None, workspace

    async def locked(_session, _workspace):
        assert _workspace is workspace
        _workspace.settings_json = {
            "workspaceSettingsV2": latest.model_dump(by_alias=True, mode="json"),
            "unrelatedSetting": "preserve",
        }
        effects.append("lock")

    async def validate(_payload, _principal, _session, _workspace_id, roles):
        assert _payload is requested
        assert {role.id for role in roles.custom_roles} == {current_role.id}
        effects.append("validate")

    monkeypatch.setattr(access, "load_workspace", scoped_loader)
    monkeypatch.setattr(access, "lock_workspace_settings", locked)
    monkeypatch.setattr(access, "_validate_teams", validate)
    monkeypatch.setattr(access, "record_workspace_change", lambda *_args, **_kwargs: effects.append("audit"))

    result = await access.update_teams(
        requested,
        object(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        session,  # type: ignore[arg-type]
    )

    saved = settings_document(workspace)
    assert result is requested
    assert saved.teams.teams[0].role_ids == [current_role.id]
    assert saved.roles.custom_roles[0].id == current_role.id
    assert saved.general.industry == "Education"
    assert workspace.settings_json["unrelatedSetting"] == "preserve"
    assert effects == ["lock", "validate", "audit"]
    assert session.commits == 1
