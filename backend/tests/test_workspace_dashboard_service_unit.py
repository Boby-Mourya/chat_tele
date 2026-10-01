"""Section 23 dashboard draft service and original API behavior."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from northstar_api.models import Workspace, WorkspaceStatus
from northstar_api.modules.workspace import access
from northstar_api.modules.workspace.contracts import (
    DashboardSettings,
    DashboardWidget,
    ExtendedBranding,
    WorkspaceSettingsBundle,
)
from northstar_api.modules.workspace.services.dashboard_service import update_workspace_dashboard
from northstar_api.modules.workspace.store import settings_document


def _workspace() -> Workspace:
    initial_layout = DashboardSettings(layout_version=1, widgets=[DashboardWidget(type="usage")])
    draft = ExtendedBranding(dashboard=initial_layout.model_copy(deep=True))
    published = ExtendedBranding(dashboard=initial_layout.model_copy(deep=True))
    document = WorkspaceSettingsBundle(
        dashboard=initial_layout,
        branding_draft=draft,
        branding_published=published,
    )
    document.general.industry = "Education"
    return Workspace(
        id=uuid4(),
        tenant_id=uuid4(),
        name="Admissions",
        slug="admissions",
        status=WorkspaceStatus.ACTIVE,
        settings_json={
            "workspaceSettingsV2": document.model_dump(by_alias=True, mode="json"),
            "unrelatedSetting": {"keep": True},
        },
        branding_json={},
    )


def test_dashboard_service_changes_draft_but_not_published_brand() -> None:
    workspace = _workspace()
    published_before = settings_document(workspace).branding_published
    assert published_before is not None
    published_json = published_before.model_dump(by_alias=True, mode="json")
    requested = DashboardSettings(layout_version=2, widgets=[DashboardWidget(type="lead-summary")])

    before = update_workspace_dashboard(workspace, requested)

    saved = settings_document(workspace)
    assert before["layoutVersion"] == 1
    assert saved.dashboard.layout_version == 2
    assert saved.branding_draft.dashboard.layout_version == 2
    assert saved.branding_draft.dashboard.widgets[0].type == "lead-summary"
    assert saved.branding_published is not None
    assert saved.branding_published.model_dump(by_alias=True, mode="json") == published_json
    assert saved.general.industry == "Education"
    assert workspace.settings_json["unrelatedSetting"] == {"keep": True}


class _Session:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


@pytest.mark.asyncio
async def test_dashboard_endpoint_keeps_lock_dual_write_audit_commit_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace()
    session = _Session()
    requested = DashboardSettings(layout_version=3, widgets=[DashboardWidget(type="usage")])
    effects: list[str] = []

    async def scoped_loader(_principal, _session):
        return None, workspace

    async def locked(_session, _workspace):
        assert _workspace is workspace
        effects.append("lock")

    async def persist(_session, _workspace, document):
        assert _session is session
        assert _workspace is workspace
        assert document.dashboard.layout_version == 3
        assert document.branding_draft.dashboard.layout_version == 3
        assert document.branding_published is not None
        assert document.branding_published.dashboard.layout_version == 1
        effects.append("dual-write")

    def audit(_session, _principal, _workspace, action, _fields, **kwargs):
        assert action == "workspace.dashboard.updated"
        assert kwargs["before"]["layoutVersion"] == 1
        assert kwargs["after"]["layoutVersion"] == 3
        effects.append("audit")

    monkeypatch.setattr(access, "load_workspace", scoped_loader)
    monkeypatch.setattr(access, "lock_workspace_settings", locked)
    monkeypatch.setattr(access, "persist_branding_document", persist)
    monkeypatch.setattr(access, "record_workspace_change", audit)

    result = await access.update_dashboard(
        requested,
        object(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        session,  # type: ignore[arg-type]
    )

    assert result is requested
    assert effects == ["lock", "dual-write", "audit"]
    assert session.commits == 1
