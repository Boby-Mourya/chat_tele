"""The dashboard runtime must never expose unpublished branding drafts."""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from northstar_api.modules.workspace import dashboard_runtime
from northstar_api.modules.workspace.contracts import (
    DashboardAppearance,
    DashboardWidget,
    ExtendedBranding,
    WorkspaceSettingsBundle,
)


@pytest.mark.asyncio
async def test_runtime_dashboard_keeps_draft_appearance_private(monkeypatch: pytest.MonkeyPatch) -> None:
    document = WorkspaceSettingsBundle()
    document.general.industry = "education"
    document.general.country = "IN"
    document.dashboard.widgets = [DashboardWidget(type="conversation-summary")]
    document.branding_draft.appearance.sidebar_style = "minimal"
    document.branding_draft.appearance.border_radius = 31
    workspace = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    tenant = SimpleNamespace(plan="starter")

    async def load_workspace(_principal, _session):
        return tenant, workspace

    async def resolve_published_brand(_session, _workspace):
        return None, 0

    monkeypatch.setattr(dashboard_runtime, "load_workspace", load_workspace)
    monkeypatch.setattr(dashboard_runtime, "settings_document", lambda _workspace: document)
    monkeypatch.setattr(dashboard_runtime, "resolve_published_workspace_brand", resolve_published_brand)
    monkeypatch.setattr(
        dashboard_runtime,
        "entitlement_for_plan",
        lambda _plan: SimpleNamespace(
            allowed_channels=[],
            crm_enabled=False,
            api_enabled=False,
            white_label_enabled=False,
            custom_domain_enabled=False,
            branded_email_enabled=False,
        ),
    )

    result = await dashboard_runtime.get_runtime_dashboard(object(), object())  # type: ignore[arg-type]

    assert result.dashboard.widgets[0].type == "conversation-summary"
    assert result.industry == "education"
    assert result.country == "IN"
    assert result.appearance == DashboardAppearance()
    assert result.appearance.sidebar_style != document.branding_draft.appearance.sidebar_style
    assert result.appearance.border_radius != document.branding_draft.appearance.border_radius


@pytest.mark.asyncio
async def test_runtime_dashboard_uses_published_appearance(monkeypatch: pytest.MonkeyPatch) -> None:
    document = WorkspaceSettingsBundle()
    document.branding_draft.appearance.sidebar_style = "minimal"
    published = ExtendedBranding()
    published.appearance.sidebar_style = "soft"
    published.appearance.border_radius = 16
    published.dashboard.widgets = [DashboardWidget(type="lead-summary")]
    workspace = SimpleNamespace(id=uuid4(), tenant_id=uuid4())

    async def load_workspace(_principal, _session):
        return SimpleNamespace(plan="starter"), workspace

    async def resolve_published_brand(_session, _workspace):
        return published, 2

    monkeypatch.setattr(dashboard_runtime, "load_workspace", load_workspace)
    monkeypatch.setattr(dashboard_runtime, "settings_document", lambda _workspace: document)
    monkeypatch.setattr(dashboard_runtime, "resolve_published_workspace_brand", resolve_published_brand)
    monkeypatch.setattr(
        dashboard_runtime,
        "entitlement_for_plan",
        lambda _plan: SimpleNamespace(
            allowed_channels=[],
            crm_enabled=False,
            api_enabled=False,
            white_label_enabled=False,
            custom_domain_enabled=False,
            branded_email_enabled=False,
        ),
    )

    result = await dashboard_runtime.get_runtime_dashboard(object(), object())  # type: ignore[arg-type]

    assert result.appearance == published.appearance
    assert result.dashboard == published.dashboard
    assert result.appearance.sidebar_style != document.branding_draft.appearance.sidebar_style
