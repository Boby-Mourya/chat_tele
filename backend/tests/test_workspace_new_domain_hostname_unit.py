"""New custom domains must be DNS hostnames; legacy stored records remain readable."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from northstar_api.modules.workspace import domains
from northstar_api.modules.workspace.contracts import DomainCreate, DomainRecord, WorkspaceSettingsBundle
from northstar_api.modules.workspace.domain_hostname import normalize_new_custom_domain_hostname


@pytest.mark.parametrize(
    ("submitted", "expected"),
    [
        ("Portal.Example.COM", "portal.example.com"),
        (" portal.example.com. ", "portal.example.com"),
        ("xn--bcher-kva.example", "xn--bcher-kva.example"),
        ("a.example.com", "a.example.com"),
    ],
)
def test_new_domain_normalization(submitted: str, expected: str) -> None:
    assert normalize_new_custom_domain_hostname(submitted) == expected


@pytest.mark.parametrize(
    "submitted",
    [
        "https://portal.example.com",
        "portal.example.com:443",
        "portal.example.com/path",
        "portal.example.com?debug=1",
        "*.example.com",
        "portal..example.com",
        "portal.example.com..",
        "-portal.example.com",
        "portal-.example.com",
        "foo_bar.example.com",
        "localhost",
        "127.0.0.1",
        "portal.例子.com",
        f"{'a' * 64}.example.com",
    ],
)
def test_new_domain_rejects_non_dns_hostname(submitted: str) -> None:
    with pytest.raises(ValueError):
        normalize_new_custom_domain_hostname(submitted)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "submitted",
    ["portal.example.com:443", "portal..example.com", "127.0.0.1", "*.example.com"],
)
async def test_create_rejects_invalid_hostname_before_writes(
    monkeypatch: pytest.MonkeyPatch, submitted: str
) -> None:
    workspace = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    document = WorkspaceSettingsBundle()
    writes: list[str] = []

    async def load_workspace(_principal: object, _session: object):
        return SimpleNamespace(plan="custom-plan"), workspace

    async def persist(*_args: object, **_kwargs: object) -> None:
        writes.append("persist")

    async def invalidate(*_args: object, **_kwargs: object) -> None:
        writes.append("invalidate")

    monkeypatch.setattr(domains, "load_workspace", load_workspace)
    monkeypatch.setattr(domains, "entitlement_for_plan", lambda _plan: SimpleNamespace(custom_domain_enabled=True))
    monkeypatch.setattr(domains, "settings_document", lambda _workspace: document)
    monkeypatch.setattr(domains, "save_document", lambda *_args: writes.append("save"))
    monkeypatch.setattr(domains, "persist_branding_document", persist)
    monkeypatch.setattr(domains, "record_workspace_change", lambda *_args, **_kwargs: writes.append("audit"))
    monkeypatch.setattr(domains, "invalidate_brand_cache", invalidate)

    with pytest.raises(HTTPException) as error:
        await domains.create_domain(
            DomainCreate(hostname=submitted),
            object(),  # type: ignore[arg-type]
            SimpleNamespace(token_id="interactive-session"),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
        )
    assert error.value.status_code == 422
    assert document.domains.domains == []
    assert writes == []


def test_legacy_domain_record_parser_is_not_tightened() -> None:
    # Compatibility for an already-persisted record is deliberately distinct
    # from rules for configuring a NEW custom domain.
    old_record = DomainRecord(
        hostname="portal.example.com:443",
        verification_name="_northstar-verify.portal.example.com",
        verification_value="older-token",
    )
    assert old_record.hostname == "portal.example.com:443"
