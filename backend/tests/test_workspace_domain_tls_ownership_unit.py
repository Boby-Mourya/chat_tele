"""A failed DNS/dispatch state cannot authorize a custom-domain TLS check."""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from northstar_api.modules.branding.services.domain_service import TLS_ELIGIBLE_DOMAIN_STATUSES
from northstar_api.modules.workspace import domains
from northstar_api.modules.workspace.contracts import DomainRecord, WorkspaceSettingsBundle


def _domain(status: str) -> DomainRecord:
    domain = DomainRecord(
        hostname="portal.example.com",
        verification_name="_northstar-verify.portal.example.com",
        verification_value="ownership-token",
    )
    domain.status = status  # type: ignore[assignment]
    return domain


async def _already_locked(_session: object, _workspace: object) -> None:
    """Route unit tests isolate TLS behavior; lock mechanics have dedicated tests."""
    return None


@pytest.mark.parametrize(
    "domain_status",
    ["pending", "dns_pending", "verifying", "failed", "disabled", "active"],
)
@pytest.mark.asyncio
async def test_activation_rejects_domains_without_verified_dns(
    monkeypatch: pytest.MonkeyPatch,
    domain_status: str,
) -> None:
    domain = _domain(domain_status)
    document = WorkspaceSettingsBundle()
    document.domains.domains.append(domain)
    workspace = SimpleNamespace(id=uuid4(), tenant_id=uuid4())

    async def load_workspace(_principal: object, _session: object):
        return None, workspace

    def forbidden_side_effect(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("A rejected domain must not persist or enqueue TLS work")

    monkeypatch.setattr(domains, "load_workspace", load_workspace)
    monkeypatch.setattr(domains, "lock_workspace_settings", _already_locked)
    monkeypatch.setattr(domains, "settings_document", lambda _workspace: document)
    monkeypatch.setattr(domains, "save_document", forbidden_side_effect)
    monkeypatch.setattr(domains, "_enqueue", forbidden_side_effect)

    with pytest.raises(HTTPException) as error:
        await domains.check_domain_activation(
            domain.id,
            object(),  # type: ignore[arg-type]
            SimpleNamespace(token_id="interactive-session"),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
        )

    assert error.value.status_code == 409
    assert domain.status == domain_status


@pytest.mark.parametrize("domain_status", ["verified", "certificate_pending"])
@pytest.mark.asyncio
async def test_activation_preserves_verified_domain_retry(
    monkeypatch: pytest.MonkeyPatch,
    domain_status: str,
) -> None:
    domain = _domain(domain_status)
    document = WorkspaceSettingsBundle()
    document.domains.domains.append(domain)
    workspace = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    queued: list[str] = []
    commits: list[str] = []

    async def load_workspace(_principal: object, _session: object):
        return None, workspace

    async def persist_branding_document(*_args: object, **_kwargs: object) -> None:
        return None

    async def invalidate_brand_cache(*_args: object, **_kwargs: object) -> None:
        return None

    class Session:
        async def commit(self) -> None:
            commits.append("committed")

    def enqueue(task_name: str, **_kwargs: object) -> bool:
        queued.append(task_name)
        return True

    monkeypatch.setattr(domains, "load_workspace", load_workspace)
    monkeypatch.setattr(domains, "lock_workspace_settings", _already_locked)
    monkeypatch.setattr(domains, "settings_document", lambda _workspace: document)
    monkeypatch.setattr(domains, "save_document", lambda *_args: None)
    monkeypatch.setattr(domains, "persist_branding_document", persist_branding_document)
    monkeypatch.setattr(domains, "record_workspace_change", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(domains, "invalidate_brand_cache", invalidate_brand_cache)
    monkeypatch.setattr(domains, "_enqueue", enqueue)

    result = await domains.check_domain_activation(
        domain.id,
        object(),  # type: ignore[arg-type]
        SimpleNamespace(token_id="interactive-session"),  # type: ignore[arg-type]
        Session(),  # type: ignore[arg-type]
    )

    assert domain_status in TLS_ELIGIBLE_DOMAIN_STATUSES
    assert result.status == "certificate_pending"
    assert commits == ["committed"]
    assert queued == ["northstar.check_workspace_brand_tls"]


def test_domain_tls_eligibility_never_includes_ambiguous_failure() -> None:
    assert TLS_ELIGIBLE_DOMAIN_STATUSES == frozenset({"verified", "certificate_pending"})
    assert "failed" not in TLS_ELIGIBLE_DOMAIN_STATUSES
