from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import structlog
from redis.exceptions import RedisError

from northstar_api.services.rate_limit import redis_services

logger = structlog.get_logger(__name__)
_CACHE_TTL_SECONDS = 300
_VERSION_CACHE_TTL_SECONDS = 3600


def _workspace_key(workspace_id: UUID) -> str:
    return f"northstar:brand:workspace:{workspace_id}"


def _domain_key(hostname: str) -> str:
    return f"northstar:brand:domain:{hostname.strip().lower().rstrip('.')}"


def _version_key(workspace_id: UUID, version: int) -> str:
    return f"northstar:brand:version:{workspace_id}:{version}"


async def _read_json(key: str, *, scope: str) -> dict[str, Any] | None:
    try:
        raw = await redis_services.client.get(key)
    except RedisError as exc:
        logger.warning("brand_cache_read_unavailable", scope=scope, error=type(exc).__name__)
        return None
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


async def _write_json(key: str, payload: dict[str, Any], *, ttl: int, scope: str) -> None:
    try:
        await redis_services.client.set(
            key,
            json.dumps(payload, separators=(",", ":")),
            ex=ttl,
        )
    except RedisError as exc:
        logger.warning("brand_cache_write_unavailable", scope=scope, error=type(exc).__name__)


async def cached_workspace_brand(workspace_id: UUID) -> dict[str, Any] | None:
    return await _read_json(_workspace_key(workspace_id), scope="workspace")


async def cache_workspace_brand(workspace_id: UUID, payload: dict[str, Any]) -> None:
    await _write_json(
        _workspace_key(workspace_id),
        payload,
        ttl=_CACHE_TTL_SECONDS,
        scope="workspace",
    )


async def cached_domain_brand(hostname: str) -> dict[str, Any] | None:
    return await _read_json(_domain_key(hostname), scope="domain")


async def cache_domain_brand(hostname: str, payload: dict[str, Any]) -> None:
    await _write_json(
        _domain_key(hostname),
        payload,
        ttl=_CACHE_TTL_SECONDS,
        scope="domain",
    )


async def cached_version_brand(workspace_id: UUID, version: int) -> dict[str, Any] | None:
    if version <= 0:
        return None
    return await _read_json(_version_key(workspace_id, version), scope="version")


async def cache_version_brand(workspace_id: UUID, version: int, payload: dict[str, Any]) -> None:
    if version <= 0:
        return
    await _write_json(
        _version_key(workspace_id, version),
        payload,
        ttl=_VERSION_CACHE_TTL_SECONDS,
        scope="version",
    )


async def invalidate_brand_cache(
    workspace_id: UUID,
    *,
    hostnames: list[str] | tuple[str, ...] = (),
    version: int | None = None,
) -> None:
    # Immutable version keys are intentionally retained. Publishing invalidates
    # only mutable workspace/domain aliases and announces the new version.
    keys = [_workspace_key(workspace_id), *[_domain_key(hostname) for hostname in hostnames if hostname]]
    event = {
        "workspaceId": str(workspace_id),
        "version": version,
        "domains": [hostname for hostname in hostnames if hostname],
    }
    try:
        if keys:
            await redis_services.client.delete(*keys)
        await redis_services.client.publish(
            "northstar:brand-updated",
            json.dumps(event, separators=(",", ":")),
        )
    except RedisError as exc:
        logger.warning("brand_cache_invalidation_unavailable", error=type(exc).__name__)
