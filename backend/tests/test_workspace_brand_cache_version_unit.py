from __future__ import annotations

from uuid import uuid4

import pytest

from northstar_api.models import Workspace
from northstar_api.modules.branding.models import WorkspaceBrand
from northstar_api.modules.branding.services import brand_resolution_service
from northstar_api.modules.workspace.contracts import ExtendedBranding


class _Session:
    def __init__(self, row: WorkspaceBrand | None = None) -> None:
        self.row = row
        self.queries = 0

    async def scalar(self, _statement):
        self.queries += 1
        return self.row


def _workspace() -> Workspace:
    return Workspace(
        id=uuid4(),
        tenant_id=uuid4(),
        name="Test workspace",
        slug="test-workspace",
        settings_json={},
        branding_json={},
    )


@pytest.mark.asyncio
async def test_workspace_cache_roundtrip_retains_published_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace()
    brand = ExtendedBranding()
    brand.identity.company_name = "Published Academy"
    row = WorkspaceBrand(
        workspace_id=workspace.id,
        tenant_id=workspace.tenant_id,
        draft_json={},
        published_json=brand.model_dump(by_alias=True, mode="json"),
        published_version=7,
    )
    session = _Session(row)
    alias: dict = {}
    immutable: dict = {}

    async def read_alias(_workspace_id):
        return alias or None

    async def write_alias(_workspace_id, payload):
        alias.clear()
        alias.update(payload)

    async def read_version(_workspace_id, _version):
        return immutable or None

    async def write_version(_workspace_id, _version, payload):
        immutable.update(payload)

    monkeypatch.setattr(brand_resolution_service, "cached_workspace_brand", read_alias)
    monkeypatch.setattr(brand_resolution_service, "cache_workspace_brand", write_alias)
    monkeypatch.setattr(brand_resolution_service, "cached_version_brand", read_version)
    monkeypatch.setattr(brand_resolution_service, "cache_version_brand", write_version)

    first, first_version = await brand_resolution_service.resolve_published_workspace_brand(
        session,  # type: ignore[arg-type]
        workspace,
    )
    second, second_version = await brand_resolution_service.resolve_published_workspace_brand(
        session,  # type: ignore[arg-type]
        workspace,
    )

    assert first is not None and second is not None
    assert first.identity.company_name == second.identity.company_name == "Published Academy"
    assert first_version == second_version == 7
    assert session.queries == 1  # The second lookup is served by the cache.
    assert alias["__published_brand_version"] == 7
    assert "__published_brand_version" not in immutable  # Version snapshots remain unchanged.


@pytest.mark.asyncio
async def test_legacy_workspace_cache_entry_remains_readable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace()
    old_cache = ExtendedBranding().model_dump(by_alias=True, mode="json")

    async def read_alias(_workspace_id):
        return old_cache

    monkeypatch.setattr(brand_resolution_service, "cached_workspace_brand", read_alias)
    session = _Session()
    brand, version = await brand_resolution_service.resolve_published_workspace_brand(
        session,  # type: ignore[arg-type]
        workspace,
    )

    assert brand is not None
    assert version == 0  # Older cache aliases expire under their existing short TTL.
    assert session.queries == 0
