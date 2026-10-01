"""A queued domain worker must not overwrite changes made during DNS/TLS I/O."""
from __future__ import annotations

from uuid import uuid4

import pytest

from northstar_api.models import Workspace, WorkspaceStatus
from northstar_api.modules.branding.workers.domain_tasks import _refresh_domain_for_result
from northstar_api.modules.workspace.contracts import DomainRecord, WorkspaceSettingsBundle
from northstar_api.modules.workspace.store import save_document


def _domain(status: str = "certificate_pending") -> DomainRecord:
    domain = DomainRecord(
        hostname="portal.example.com",
        verification_name="_northstar-verify.portal.example.com",
        verification_value="original-ownership-token",
    )
    domain.status = status  # type: ignore[assignment]
    return domain


def _workspace(domain: DomainRecord) -> Workspace:
    workspace = Workspace(
        id=uuid4(),
        tenant_id=uuid4(),
        name="Workspace",
        slug="workspace",
        status=WorkspaceStatus.ACTIVE,
        settings_json={},
        branding_json={},
    )
    document = WorkspaceSettingsBundle()
    document.domains.domains.append(domain)
    save_document(workspace, document)
    return workspace


class _RefreshSession:
    def __init__(self, updated_document: WorkspaceSettingsBundle, *, active: bool = True) -> None:
        self.updated_document = updated_document
        self.active = active
        self.refresh_calls = 0

    async def refresh(self, workspace: Workspace, *, attribute_names, with_for_update) -> None:
        assert attribute_names == ["settings_json", "status"]
        assert with_for_update is True
        self.refresh_calls += 1
        # Emulate an administrator's committed change becoming visible when
        # the worker reloads the locked workspace row after network I/O.
        save_document(workspace, self.updated_document)
        workspace.status = WorkspaceStatus.ACTIVE if self.active else WorkspaceStatus.ARCHIVED


def _document(*domains: DomainRecord) -> WorkspaceSettingsBundle:
    document = WorkspaceSettingsBundle()
    document.domains.domains.extend(domains)
    return document


@pytest.mark.parametrize("current_status", ["disabled", "failed", "verifying", "dns_pending", "active"])
@pytest.mark.asyncio
async def test_tls_worker_does_not_reactivate_changed_domain(current_status: str) -> None:
    original = _domain()
    workspace = _workspace(original)
    current = original.model_copy(deep=True)
    current.status = current_status  # type: ignore[assignment]
    session = _RefreshSession(_document(current))

    result = await _refresh_domain_for_result(
        session,  # type: ignore[arg-type]
        workspace,
        original.id,
        hostname=original.hostname,
        allowed_statuses=frozenset({"verified", "certificate_pending"}),
    )

    assert result is None
    assert session.refresh_calls == 1
    assert current.status == current_status


@pytest.mark.asyncio
async def test_tls_worker_uses_current_locked_document_for_eligible_retry() -> None:
    original = _domain()
    workspace = _workspace(original)
    current = original.model_copy(deep=True)
    current.status = "verified"
    session = _RefreshSession(_document(current))

    result = await _refresh_domain_for_result(
        session,  # type: ignore[arg-type]
        workspace,
        original.id,
        hostname=original.hostname,
        allowed_statuses=frozenset({"verified", "certificate_pending"}),
    )

    assert result is not None
    _, refreshed_domain = result
    assert refreshed_domain.status == "verified"
    assert session.refresh_calls == 1


@pytest.mark.asyncio
async def test_dns_worker_does_not_apply_result_after_token_rotation() -> None:
    original = _domain("verifying")
    workspace = _workspace(original)
    rotated = original.model_copy(deep=True)
    rotated.verification_value = "replacement-token"
    session = _RefreshSession(_document(rotated))

    result = await _refresh_domain_for_result(
        session,  # type: ignore[arg-type]
        workspace,
        original.id,
        hostname=original.hostname,
        allowed_statuses=frozenset({"pending", "dns_pending", "verifying"}),
        verification_name=original.verification_name,
        verification_value=original.verification_value,
    )

    assert result is None
    assert session.refresh_calls == 1


@pytest.mark.asyncio
async def test_worker_does_not_write_removed_domain_or_archived_workspace() -> None:
    original = _domain()
    workspace = _workspace(original)
    for session in (_RefreshSession(_document()), _RefreshSession(_document(original), active=False)):
        result = await _refresh_domain_for_result(
            session,  # type: ignore[arg-type]
            workspace,
            original.id,
            hostname=original.hostname,
            allowed_statuses=frozenset({"verified", "certificate_pending"}),
        )
        assert result is None
        assert session.refresh_calls == 1
        workspace.status = WorkspaceStatus.ACTIVE
