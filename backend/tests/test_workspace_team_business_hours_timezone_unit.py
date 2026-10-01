"""Section 23: team business hours use the existing Workspace timezone policy."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from northstar_api.models import Workspace, WorkspaceStatus
from northstar_api.modules.workspace import access
from northstar_api.modules.workspace.contracts import (
    BusinessHours,
    RolesSettings,
    TeamsSettings,
    WorkspaceSettingsBundle,
    WorkspaceTeam,
)
from northstar_api.modules.workspace.store import settings_document


def _team(timezone: str, name: str = "Admissions") -> WorkspaceTeam:
    return WorkspaceTeam(
        name=name,
        business_hours=BusinessHours(
            timezone=timezone,
            schedule={"monday": ["09:00-17:30"]},
        ),
    )


def _workspace() -> Workspace:
    document = WorkspaceSettingsBundle()
    document.general.industry = "Education"
    return Workspace(
        id=uuid4(),
        tenant_id=uuid4(),
        name="Admissions",
        slug="admissions",
        status=WorkspaceStatus.ACTIVE,
        settings_json={
            "workspaceSettingsV2": document.model_dump(by_alias=True, mode="json"),
            "otherSetting": {"preserve": True},
        },
        branding_json={},
    )


@pytest.mark.asyncio
async def test_unknown_team_timezone_is_rejected_before_membership_queries() -> None:
    with pytest.raises(HTTPException) as error:
        await access._validate_teams(
            TeamsSettings(teams=[_team("Not/A_Real_Timezone")]),
            SimpleNamespace(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            uuid4(),
            RolesSettings(),
        )

    assert error.value.status_code == 422
    assert "Unknown timezone" in error.value.detail


@pytest.mark.asyncio
async def test_every_team_timezone_is_checked_not_just_the_first() -> None:
    with pytest.raises(HTTPException) as error:
        await access._validate_teams(
            TeamsSettings(teams=[_team("UTC"), _team("Not/A_Real_Timezone", "Support")]),
            SimpleNamespace(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            uuid4(),
            RolesSettings(),
        )

    assert error.value.status_code == 422


class _Session:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


@pytest.mark.asyncio
async def test_invalid_team_timezone_never_saves_audits_or_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace()
    before = dict(workspace.settings_json)
    session = _Session()
    effects: list[str] = []

    async def scoped_loader(_principal, _session):
        return None, workspace

    async def locked(_session, _workspace):
        assert _workspace is workspace
        effects.append("lock")

    monkeypatch.setattr(access, "load_workspace", scoped_loader)
    monkeypatch.setattr(access, "lock_workspace_settings", locked)
    monkeypatch.setattr(access, "record_workspace_change", lambda *_args, **_kwargs: effects.append("audit"))

    with pytest.raises(HTTPException) as error:
        await access.update_teams(
            TeamsSettings(teams=[_team("Not/A_Real_Timezone")]),
            object(),  # type: ignore[arg-type]
            SimpleNamespace(),  # type: ignore[arg-type]
            session,  # type: ignore[arg-type]
        )

    assert error.value.status_code == 422
    assert workspace.settings_json == before
    assert effects == ["lock"]
    assert session.commits == 0


@pytest.mark.asyncio
async def test_valid_team_timezone_preserves_existing_write_audit_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace()
    session = _Session()
    effects: list[str] = []
    payload = TeamsSettings(teams=[_team("Asia/Kolkata")])

    async def scoped_loader(_principal, _session):
        return None, workspace

    async def locked(_session, _workspace):
        assert _workspace is workspace
        effects.append("lock")

    async def empty_members(_session, _principal, _workspace_id):
        effects.append("members")
        return set()

    async def empty_agents(_session, _principal, _workspace_id):
        effects.append("agents")
        return set()

    monkeypatch.setattr(access, "load_workspace", scoped_loader)
    monkeypatch.setattr(access, "lock_workspace_settings", locked)
    monkeypatch.setattr(access, "_workspace_member_ids", empty_members)
    monkeypatch.setattr(access, "_workspace_agent_ids", empty_agents)
    monkeypatch.setattr(access, "record_workspace_change", lambda *_args, **_kwargs: effects.append("audit"))

    result = await access.update_teams(
        payload,
        object(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        session,  # type: ignore[arg-type]
    )

    assert result is payload
    assert settings_document(workspace).teams.teams[0].business_hours.timezone == "Asia/Kolkata"
    assert settings_document(workspace).general.industry == "Education"
    assert workspace.settings_json["otherSetting"] == {"preserve": True}
    assert effects == ["lock", "members", "agents", "audit"]
    assert session.commits == 1
