"""A failed queue dispatch must not overwrite a newer Workspace domain change."""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from northstar_api.models import Workspace, WorkspaceStatus
from northstar_api.modules.workspace import domains
from northstar_api.modules.workspace.contracts import DomainRecord, WorkspaceSettingsBundle
from northstar_api.modules.workspace.store import save_document, settings_document


def _domain(status: str, hostname: str = "portal.example.com") -> DomainRecord:
    domain = DomainRecord(
        hostname=hostname,
        verification_name=f"_northstar-verify.{hostname}",
        verification_value="original-ownership-token",
    )
    domain.status = status  # type: ignore[assignment]
    return domain


def _document(*records: DomainRecord) -> WorkspaceSettingsBundle:
    document = WorkspaceSettingsBundle()
    document.domains.domains.extend(records)
    return document


def _workspace(document: WorkspaceSettingsBundle) -> Workspace:
    workspace = Workspace(
        id=uuid4(),
        tenant_id=uuid4(),
        name="Admissions",
        slug="admissions",
        status=WorkspaceStatus.ACTIVE,
        settings_json={},
        branding_json={},
    )
    save_document(workspace, document)
    return workspace


class _Session:
    def __init__(self, updated: WorkspaceSettingsBundle, *, active: bool = True) -> None:
        self.updated = updated
        self.active = active
        self.refreshes = 0
        self.commits = 0
        self.rollbacks = 0

    async def refresh(self, workspace: Workspace, *, attribute_names, with_for_update) -> None:
        assert attribute_names == ["settings_json", "status"]
        assert with_for_update is True
        self.refreshes += 1
        # The row-lock refresh reveals an administrator's newer committed JSON.
        save_document(workspace, self.updated)
        workspace.status = WorkspaceStatus.ACTIVE if self.active else WorkspaceStatus.ARCHIVED

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


async def _mark(
    monkeypatch: pytest.MonkeyPatch,
    original: DomainRecord,
    current: WorkspaceSettingsBundle,
    *,
    operation: str,
    active: bool = True,
) -> tuple[_Session, Workspace, list[str]]:
    workspace = _workspace(_document(original))
    session = _Session(current, active=active)
    actions: list[str] = []

    async def persist(*_args, **_kwargs) -> None:
        actions.append("persist")

    async def invalidate(*_args, **_kwargs) -> None:
        actions.append("invalidate")

    monkeypatch.setattr(domains, "persist_branding_document", persist)
    monkeypatch.setattr(
        domains,
        "record_workspace_change",
        lambda _session, _principal, _workspace, action, *_args, **_kwargs: actions.append(action),
    )
    monkeypatch.setattr(domains, "invalidate_brand_cache", invalidate)
    await domains._mark_dispatch_failed(
        session=session,  # type: ignore[arg-type]
        principal=SimpleNamespace(),  # type: ignore[arg-type]
        request=SimpleNamespace(),  # type: ignore[arg-type]
        workspace=workspace,
        document=settings_document(workspace),
        domain=original,
        operation=operation,
    )
    return session, workspace, actions


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "queued_status", "changed_status"),
    [
        ("verification", "verifying", "disabled"),
        ("verification", "verifying", "verified"),
        ("activation", "certificate_pending", "disabled"),
        ("activation", "certificate_pending", "active"),
        ("activation", "certificate_pending", "dns_pending"),
    ],
)
async def test_dispatch_failure_does_not_overwrite_newer_status(
    monkeypatch: pytest.MonkeyPatch, operation: str, queued_status: str, changed_status: str
) -> None:
    original = _domain(queued_status)
    updated = original.model_copy(deep=True)
    updated.status = changed_status  # type: ignore[assignment]
    session, workspace, actions = await _mark(monkeypatch, original, _document(updated), operation=operation)
    assert session.refreshes == 1
    assert session.commits == 0
    assert session.rollbacks == 1
    assert actions == []
    assert settings_document(workspace).domains.domains[0].status == changed_status


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,queued_status",
    [("verification", "verifying"), ("activation", "certificate_pending")],
)
async def test_dispatch_failure_ignores_removed_domain_and_archived_workspace(
    monkeypatch: pytest.MonkeyPatch, operation: str, queued_status: str
) -> None:
    original = _domain(queued_status)
    for current, active in ((_document(), True), (_document(original), False)):
        session, _, actions = await _mark(
            monkeypatch, original, current, operation=operation, active=active
        )
        assert session.refreshes == 1
        assert session.rollbacks == 1
        assert session.commits == 0
        assert actions == []


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["hostname", "verification_name", "verification_value"])
async def test_dispatch_failure_ignores_replaced_verification_credentials(
    monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    original = _domain("verifying")
    changed = original.model_copy(deep=True)
    setattr(changed, field, "replacement.example.com" if field == "hostname" else "rotated-token")
    session, _, actions = await _mark(
        monkeypatch, original, _document(changed), operation="verification"
    )
    assert session.rollbacks == 1
    assert session.commits == 0
    assert actions == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,queued_status",
    [("verification", "verifying"), ("activation", "certificate_pending")],
)
async def test_unchanged_failed_dispatch_persists_and_audits_without_discarding_other_domains(
    monkeypatch: pytest.MonkeyPatch, operation: str, queued_status: str
) -> None:
    original = _domain(queued_status)
    current = original.model_copy(deep=True)
    unrelated = _domain("active", "other.example.com")
    session, workspace, actions = await _mark(
        monkeypatch, original, _document(current, unrelated), operation=operation
    )
    assert session.refreshes == 1
    assert session.commits == 1
    assert session.rollbacks == 0
    assert actions == ["persist", f"workspace.domain.{operation}.dispatch_failed", "invalidate"]
    stored = settings_document(workspace).domains.domains
    assert stored[0].status == "failed"
    assert "retry this operation" in stored[0].failure_reason
    assert stored[1].id == unrelated.id
    assert stored[1].status == "active"
