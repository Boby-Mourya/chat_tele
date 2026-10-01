"""The original Workspace PATCH must participate in the same settings write lock."""

from __future__ import annotations

from importlib import import_module
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from northstar_api.models import Workspace, WorkspaceStatus
from northstar_api.modules.workspace.contracts import WorkspaceSettingsBundle
from northstar_api.workspace_contract import WorkspacePreferences

legacy = import_module("northstar_api.routers.workspace")


class _Session:
    def __init__(self, latest_settings: dict[str, object], *, status: WorkspaceStatus = WorkspaceStatus.ACTIVE):
        self.latest_settings = latest_settings
        self.status = status
        self.locked = False
        self.commits = 0
        self.refreshes: list[tuple[str, ...] | None] = []

    async def refresh(self, workspace, *, attribute_names=None, with_for_update=None):
        self.refreshes.append(tuple(attribute_names) if attribute_names is not None else None)
        if with_for_update:
            self.locked = True
            workspace.settings_json = self.latest_settings
            workspace.status = self.status

    async def commit(self):
        self.commits += 1


def _workspace() -> Workspace:
    return Workspace(
        id=uuid4(),
        tenant_id=uuid4(),
        name="Admissions",
        slug="admissions",
        status=WorkspaceStatus.ACTIVE,
        settings_json={"preferences": {"timezone": "UTC"}},
        branding_json={},
    )


@pytest.mark.asyncio
async def test_legacy_patch_preserves_concurrent_workspace_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace()
    latest = {
        "workspaceSettingsV2": WorkspaceSettingsBundle().model_dump(by_alias=True, mode="json"),
        "customExistingSetting": {"preserve": True},
    }
    session = _Session(latest)
    principal = SimpleNamespace(
        tenant_id=workspace.tenant_id,
        workspace_id=workspace.id,
        user_id=uuid4(),
        role=SimpleNamespace(value="member"),
    )

    async def scoped_loader(_tenant_id, _workspace_id, _user_id, _session):
        return SimpleNamespace(plan="enterprise"), workspace, SimpleNamespace(), 1

    def visible_response(_tenant, current_workspace, _membership, _count, _role):
        assert session.locked
        return current_workspace.settings_json

    monkeypatch.setattr(legacy, "_load_workspace", scoped_loader)
    monkeypatch.setattr(legacy, "_workspace_response", visible_response)

    result = await legacy.update_workspace(
        legacy.WorkspacePatch(preferences=WorkspacePreferences(timezone="Asia/Kolkata")),
        principal,  # type: ignore[arg-type]
        session,  # type: ignore[arg-type]
    )

    assert result["customExistingSetting"] == {"preserve": True}
    assert "workspaceSettingsV2" in result
    assert result["preferences"]["timezone"] == "Asia/Kolkata"
    assert session.refreshes[0] == ("settings_json", "branding_json", "status", "created_by")
    assert session.commits == 1


@pytest.mark.asyncio
async def test_legacy_patch_rejects_workspace_archived_after_scoped_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace()
    session = _Session({}, status=WorkspaceStatus.ARCHIVED)
    principal = SimpleNamespace(tenant_id=workspace.tenant_id, workspace_id=workspace.id, user_id=uuid4())

    async def scoped_loader(_tenant_id, _workspace_id, _user_id, _session):
        return SimpleNamespace(), workspace, SimpleNamespace(), 1

    monkeypatch.setattr(legacy, "_load_workspace", scoped_loader)
    with pytest.raises(HTTPException) as error:
        await legacy.update_workspace(
            legacy.WorkspacePatch(name="New name"),
            principal,  # type: ignore[arg-type]
            session,  # type: ignore[arg-type]
        )

    assert error.value.status_code == 404
    assert session.locked
    assert session.commits == 0
    assert workspace.name == "Admissions"
