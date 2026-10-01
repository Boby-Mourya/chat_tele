"""Workspace domain creation must preserve the global hostname constraint and bundle limit."""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from northstar_api.modules.workspace import domains
from northstar_api.modules.workspace.contracts import DomainCreate, DomainRecord, WorkspaceSettingsBundle


class _Session:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def _domain(hostname: str, *, status: str = "dns_pending") -> DomainRecord:
    domain = DomainRecord(
        hostname=hostname,
        verification_name=f"_northstar-verify.{hostname}",
        verification_value="ownership-token",
    )
    domain.status = status  # type: ignore[assignment]
    return domain


def _setup(monkeypatch: pytest.MonkeyPatch, document: WorkspaceSettingsBundle):
    workspace = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    session = _Session()
    side_effects: list[str] = []

    async def load_workspace(_principal: object, _session: object):
        return SimpleNamespace(plan="custom-plan"), workspace

    async def lock_workspace_settings(_session: object, _workspace: object) -> None:
        return None

    async def persist(*_args: object, **_kwargs: object) -> None:
        side_effects.append("persist")

    async def invalidate(*_args: object, **_kwargs: object) -> None:
        side_effects.append("invalidate")

    monkeypatch.setattr(domains, "load_workspace", load_workspace)
    monkeypatch.setattr(domains, "lock_workspace_settings", lock_workspace_settings)
    monkeypatch.setattr(domains, "entitlement_for_plan", lambda _plan: SimpleNamespace(custom_domain_enabled=True))
    monkeypatch.setattr(domains, "settings_document", lambda _workspace: document)
    monkeypatch.setattr(domains, "save_document", lambda *_args: side_effects.append("save"))
    monkeypatch.setattr(domains, "persist_branding_document", persist)
    monkeypatch.setattr(domains, "record_workspace_change", lambda *_args, **_kwargs: side_effects.append("audit"))
    monkeypatch.setattr(domains, "invalidate_brand_cache", invalidate)
    return session, side_effects


async def _create(session: _Session, hostname: str = "portal.example.com") -> DomainRecord:
    return await domains.create_domain(
        DomainCreate(hostname=hostname),
        object(),  # type: ignore[arg-type]
        SimpleNamespace(token_id="interactive-session"),  # type: ignore[arg-type]
        session,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("existing_status", ["active", "disabled", "dns_pending"])
async def test_existing_domain_is_rejected_even_when_disabled(
    monkeypatch: pytest.MonkeyPatch, existing_status: str
) -> None:
    document = WorkspaceSettingsBundle()
    document.domains.domains.append(_domain("portal.example.com", status=existing_status))
    session, side_effects = _setup(monkeypatch, document)

    with pytest.raises(HTTPException) as error:
        await _create(session, "PORTAL.EXAMPLE.COM.")

    assert error.value.status_code == 409
    assert len(document.domains.domains) == 1
    assert side_effects == []
    assert session.commits == session.rollbacks == 0


@pytest.mark.asyncio
async def test_twenty_domain_limit_rejects_before_mutating_document(monkeypatch: pytest.MonkeyPatch) -> None:
    document = WorkspaceSettingsBundle()
    document.domains.domains.extend(_domain(f"portal-{index}.example.com") for index in range(20))
    session, side_effects = _setup(monkeypatch, document)

    with pytest.raises(HTTPException) as error:
        await _create(session)

    assert error.value.status_code == 409
    assert len(document.domains.domains) == 20
    assert side_effects == []
    assert session.commits == session.rollbacks == 0


@pytest.mark.asyncio
async def test_global_hostname_collision_rolls_back_and_returns_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    document = WorkspaceSettingsBundle()
    session, side_effects = _setup(monkeypatch, document)

    async def collision(*_args: object, **_kwargs: object) -> None:
        raise IntegrityError(
            "INSERT INTO workspace_custom_domain",
            {},
            Exception('duplicate key value violates unique constraint "uq_workspace_custom_domain_hostname"'),
        )

    monkeypatch.setattr(domains, "persist_branding_document", collision)

    with pytest.raises(HTTPException) as error:
        await _create(session)

    assert error.value.status_code == 409
    assert session.rollbacks == 1
    assert session.commits == 0
    assert "invalidate" not in side_effects
    assert "audit" not in side_effects


@pytest.mark.asyncio
async def test_unrelated_integrity_errors_are_not_misreported_as_duplicate_domains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = WorkspaceSettingsBundle()
    session, side_effects = _setup(monkeypatch, document)

    async def unrelated_error(*_args: object, **_kwargs: object) -> None:
        raise IntegrityError("INSERT INTO workspace_brand", {}, Exception("foreign key violation"))

    monkeypatch.setattr(domains, "persist_branding_document", unrelated_error)

    with pytest.raises(IntegrityError):
        await _create(session)

    assert session.rollbacks == 1
    assert session.commits == 0
    assert "invalidate" not in side_effects


@pytest.mark.asyncio
async def test_new_unique_domain_keeps_existing_persistence_audit_and_cache_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = WorkspaceSettingsBundle()
    session, side_effects = _setup(monkeypatch, document)

    created = await _create(session)

    assert created.hostname == "portal.example.com"
    assert created.status == "dns_pending"
    assert len(document.domains.domains) == 1
    assert side_effects == ["save", "persist", "audit", "invalidate"]
    assert session.commits == 1
    assert session.rollbacks == 0
