from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.models import Workspace
from northstar_api.modules.workspace.brand_cache import (
    cache_version_brand,
    cache_workspace_brand,
    cached_version_brand,
    cached_workspace_brand,
)
from northstar_api.modules.workspace.contracts import ExtendedBranding
from northstar_api.modules.workspace.store import settings_document

from ..models import WorkspaceBrand


# Metadata belongs only to the mutable workspace cache alias. Immutable version
# snapshots and the public branding response keep their existing payload shape.
_WORKSPACE_CACHE_VERSION_KEY = "__published_brand_version"


def _workspace_cache_payload(branding: ExtendedBranding, version: int) -> dict[str, Any]:
    return {
        **branding.model_dump(by_alias=True, mode="json"),
        _WORKSPACE_CACHE_VERSION_KEY: version,
    }


async def resolve_published_workspace_brand(
    session: AsyncSession,
    workspace: Workspace,
) -> tuple[ExtendedBranding | None, int]:
    """Resolve published branding through cache -> normalized storage -> legacy JSON.

    Normalized persistence is authoritative once populated. The legacy workspace
    settings document remains a compatibility fallback during staged migration.
    """
    cached = await cached_workspace_brand(workspace.id)
    if cached is not None:
        # Older cache entries do not have version metadata. Accept those entries
        # during the short cache TTL rather than breaking a rolling deployment.
        cached_payload = cached.copy()
        cached_version = cached_payload.pop(_WORKSPACE_CACHE_VERSION_KEY, 0)
        try:
            branding = ExtendedBranding.model_validate(cached_payload)
            if type(cached_version) is int and cached_version >= 0:
                return branding, cached_version
        except (TypeError, ValueError):
            pass

    row = await session.scalar(
        select(WorkspaceBrand).where(
            WorkspaceBrand.tenant_id == workspace.tenant_id,
            WorkspaceBrand.workspace_id == workspace.id,
        )
    )
    if row is not None and row.published_json:
        version = int(row.published_version or 0)
        if version > 0:
            version_cached = await cached_version_brand(workspace.id, version)
            if version_cached is not None:
                try:
                    branding = ExtendedBranding.model_validate(version_cached)
                    await cache_workspace_brand(
                        workspace.id,
                        _workspace_cache_payload(branding, version),
                    )
                    return branding, version
                except (TypeError, ValueError):
                    pass
        try:
            branding = ExtendedBranding.model_validate(row.published_json)
        except (TypeError, ValueError):
            branding = None
        if branding is not None:
            payload = branding.model_dump(by_alias=True, mode="json")
            if version > 0:
                await cache_version_brand(workspace.id, version, payload)
            await cache_workspace_brand(
                workspace.id,
                _workspace_cache_payload(branding, version),
            )
            return branding, version

    document = settings_document(workspace)
    branding = document.branding_published
    if branding is None:
        return None, 0
    version = max((item.version for item in document.branding_versions), default=0)
    payload = branding.model_dump(by_alias=True, mode="json")
    if version > 0:
        await cache_version_brand(workspace.id, version, payload)
    await cache_workspace_brand(
        workspace.id,
        _workspace_cache_payload(branding, version),
    )
    return branding, version


__all__ = ["resolve_published_workspace_brand"]
