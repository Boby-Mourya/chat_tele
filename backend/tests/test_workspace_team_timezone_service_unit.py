"""Team service must not persist invalid timezones when called outside HTTP."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException

from northstar_api.models import Workspace, WorkspaceStatus
from northstar_api.modules.workspace.contracts import (
    BusinessHours,
    TeamsSettings,
    WorkspaceSettingsBundle,
    WorkspaceTeam,
)
from northstar_api.modules.workspace.services.team_service import update_workspace_teams
from northstar_api.modules.workspace.store import settings_document


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
            "otherSetting": "preserve",
        },
        branding_json={},
    )


def test_service_rejects_unknown_team_timezone_without_mutating_workspace() -> None:
    workspace = _workspace()
    before = dict(workspace.settings_json)
    payload = TeamsSettings(
        teams=[
            WorkspaceTeam(name="Admissions", business_hours=BusinessHours(timezone="UTC")),
            WorkspaceTeam(name="Support", business_hours=BusinessHours(timezone="Not/A_Real_Timezone")),
        ]
    )

    with pytest.raises(HTTPException) as error:
        update_workspace_teams(workspace, payload)

    assert error.value.status_code == 422
    assert workspace.settings_json == before
    assert settings_document(workspace).general.industry == "Education"


def test_service_accepts_valid_team_timezone_without_changing_unrelated_settings() -> None:
    workspace = _workspace()
    payload = TeamsSettings(
        teams=[WorkspaceTeam(name="Admissions", business_hours=BusinessHours(timezone="Asia/Kolkata"))]
    )

    before = update_workspace_teams(workspace, payload)

    assert before["teams"] == []
    assert settings_document(workspace).teams.teams[0].business_hours.timezone == "Asia/Kolkata"
    assert settings_document(workspace).general.industry == "Education"
    assert workspace.settings_json["otherSetting"] == "preserve"
