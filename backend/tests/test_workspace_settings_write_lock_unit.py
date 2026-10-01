"""Section 23: shared Workspace JSON writers must reload under a row lock."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from northstar_api.models import Workspace, WorkspaceStatus
from northstar_api.modules.workspace import domains, settings
from northstar_api.modules.workspace.contracts import (
    DomainCreate,
    DomainRecord,
    NotificationSettings,
    WorkspaceSettingsBundle,
)
from northstar_api.modules.workspace.repositories.workspace_write_lock import lock_workspace_settings
from northstar_api.modules.workspace.store import settings_document


class _Session:
    def __init__(
        self,
        replacement: dict[str, object],
        *,
        status: WorkspaceStatus = WorkspaceStatus.ACTIVE,
        current_owner=None,
    ):
        self.replacement = replacement
        self.status = status
        self.current_owner = current_owner
        self.refreshes: list[tuple[object, tuple[str, ...], object]] = []
        self.commits = 0

    async def refresh(self, workspace, *, attribute_names, with_for_update):
        self.refreshes.append((workspace, tuple(attribute_names), with_for_update))
        workspace.settings_json = self.replacement
        workspace.branding_json = {"companyName": "Current brand"}
        workspace.status = self.status
        if self.current_owner is not None:
            workspace.created_by = self.current_owner

    async def commit(self):
        self.commits += 1


def _workspace(document: WorkspaceSettingsBundle) -> Workspace:
    return Workspace(
        id=uuid4(),
        tenant_id=uuid4(),
        name="Admissions",
        slug="admissions",
        status=WorkspaceStatus.ACTIVE,
        settings_json={"workspaceSettingsV2": document.model_dump(by_alias=True, mode="json")},
        branding_json={},
    )


def _record(hostname: str) -> DomainRecord:
    return DomainRecord(
        hostname=hostname,
        verification_name=f"_northstar-verify.{hostname}",
        verification_value="test-verification-token",
    )


@pytest.mark.asyncio
async def test_write_lock_refreshes_current_json_and_refuses_archived_workspace() -> None:
    workspace = _workspace(WorkspaceSettingsBundle())
    replacement = {"workspaceSettingsV2": {}, "otherSetting": "preserve"}
    latest_owner = uuid4()
    session = _Session(replacement, current_owner=latest_owner)
    await lock_workspace_settings(session, workspace)  # type: ignore[arg-type]
    assert session.refreshes == [
        (workspace, ("settings_json", "branding_json", "status", "created_by"), True)
    ]
    assert workspace.settings_json["otherSetting"] == "preserve"
    assert workspace.branding_json == {"companyName": "Current brand"}
    assert workspace.created_by == latest_owner

    session.status = WorkspaceStatus.ARCHIVED
    with pytest.raises(HTTPException) as error:
        await lock_workspace_settings(session, workspace)  # type: ignore[arg-type]
    assert error.value.status_code == 404
    assert session.commits == 0


@pytest.mark.asyncio
async def test_notifications_update_preserves_concurrent_general_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initial = WorkspaceSettingsBundle()
    initial.general.industry = "Old industry"
    workspace = _workspace(initial)
    current = WorkspaceSettingsBundle()
    current.general.industry = "Education"
    replacement = {
        "workspaceSettingsV2": current.model_dump(by_alias=True, mode="json"),
        "otherSetting": "preserve",
    }
    session = _Session(replacement)
    observed: list[str] = []

    async def scoped_loader(_principal, _session):
        return None, workspace

    def capture_audit(*_args, **_kwargs):
        observed.append("audit")

    monkeypatch.setattr(settings, "load_workspace", scoped_loader)
    monkeypatch.setattr(settings, "record_workspace_change", capture_audit)
    payload = NotificationSettings(weekly_digest=True)
    result = await settings.update_notifications(
        payload,
        object(),  # type: ignore[arg-type]
        SimpleNamespace(token_id="interactive-session"),  # type: ignore[arg-type]
        session,  # type: ignore[arg-type]
    )
    persisted = settings_document(workspace)
    assert result.weekly_digest is True
    assert persisted.notifications.weekly_digest is True
    assert persisted.general.industry == "Education"
    assert workspace.settings_json["otherSetting"] == "preserve"
    assert session.refreshes[0][2] is True
    assert observed == ["audit"]
    assert session.commits == 1


@pytest.mark.asyncio
async def test_domain_creation_checks_fresh_hostnames_after_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(WorkspaceSettingsBundle())
    current = WorkspaceSettingsBundle()
    current.domains.domains.append(_record("portal.example.com"))
    session = _Session({"workspaceSettingsV2": current.model_dump(by_alias=True, mode="json")})
    effects: list[str] = []

    async def scoped_loader(_principal, _session):
        return SimpleNamespace(plan="enterprise"), workspace

    async def forbidden_persist(*_args, **_kwargs):
        effects.append("persist")

    monkeypatch.setattr(domains, "load_workspace", scoped_loader)
    monkeypatch.setattr(domains, "entitlement_for_plan", lambda _plan: SimpleNamespace(custom_domain_enabled=True))
    monkeypatch.setattr(domains, "persist_branding_document", forbidden_persist)
    with pytest.raises(HTTPException) as error:
        await domains.create_domain(
            DomainCreate(hostname="PORTAL.EXAMPLE.COM"),
            object(),  # type: ignore[arg-type]
            SimpleNamespace(token_id="interactive-session"),  # type: ignore[arg-type]
            session,  # type: ignore[arg-type]
        )
    assert error.value.status_code == 409
    assert session.refreshes[0][2] is True
    assert len(settings_document(workspace).domains.domains) == 1
    assert effects == []
    assert session.commits == 0
