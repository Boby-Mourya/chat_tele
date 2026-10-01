"""Server-owned authorization for the platform control plane."""

from __future__ import annotations

import json
import os

PLATFORM_PERMISSIONS = frozenset({
    "platform.overview.read",
    "platform.tenants.read",
    "platform.tenants.manage",
    "platform.billing.manage",
    "platform.support.impersonate",
    "platform.system.read",
    "platform.audit.read",
    "platform.admins.manage",
})

PLATFORM_ROLE_GRANTS: dict[str, frozenset[str]] = {
    "owner": PLATFORM_PERMISSIONS,
    "operations": frozenset({
        "platform.overview.read", "platform.tenants.read", "platform.system.read", "platform.audit.read",
    }),
    "billing": frozenset({"platform.overview.read", "platform.tenants.read", "platform.billing.manage"}),
    "support": frozenset({
        "platform.overview.read", "platform.tenants.read", "platform.support.impersonate",
    }),
    "auditor": frozenset({"platform.overview.read", "platform.tenants.read", "platform.audit.read"}),
}


def platform_admin_emails(raw: str | None = None) -> frozenset[str]:
    value = os.getenv("PLATFORM_ADMIN_EMAILS", "") if raw is None else raw
    normalized = value.strip()
    if not normalized:
        return frozenset()
    values: list[object]
    if normalized.startswith("["):
        try:
            decoded = json.loads(normalized)
        except json.JSONDecodeError:
            decoded = []
        values = decoded if isinstance(decoded, list) else []
    else:
        values = normalized.split(",")
    return frozenset(str(item).strip().lower() for item in values if str(item).strip())


def platform_admin_permissions(email: str, raw: str | None = None) -> frozenset[str]:
    configured = os.getenv("PLATFORM_ADMIN_PERMISSIONS", "") if raw is None else raw
    if not configured.strip():
        return PLATFORM_PERMISSIONS
    try:
        decoded = json.loads(configured)
    except json.JSONDecodeError:
        return frozenset()
    if not isinstance(decoded, dict):
        return frozenset()
    value = decoded.get(email.strip().lower(), [])
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, list):
        return frozenset()
    return frozenset(
        item.strip()
        for item in value
        if isinstance(item, str) and item.strip() in PLATFORM_PERMISSIONS
    )


def platform_role_permissions(role: str, configured: object = None) -> frozenset[str]:
    """Return a validated role grant, optionally narrowed by stored permissions."""
    base = PLATFORM_ROLE_GRANTS.get(role.strip().lower(), frozenset())
    if not isinstance(configured, list):
        return base
    selected = frozenset(
        value.strip() for value in configured
        if isinstance(value, str) and value.strip() in PLATFORM_PERMISSIONS
    )
    return base if not selected else base & selected
