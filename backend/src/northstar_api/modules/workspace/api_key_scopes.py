from __future__ import annotations

API_KEY_SCOPE_PERMISSIONS: dict[str, frozenset[str]] = {
    "workspace:read": frozenset({"workspace.view"}),
    "conversations:read": frozenset({"conversations.view"}),
    "conversations:write": frozenset({"conversations.view", "conversations.reply", "conversations.resolve", "conversations.assign"}),
    "contacts:read": frozenset({"leads.view"}),
    "leads:write": frozenset({"leads.view", "leads.update"}),
    "agents:read": frozenset({"agents.view"}),
    "analytics:read": frozenset({"analytics.view"}),
    "webhooks:manage": frozenset({"integrations.view", "integrations.manage"}),
}

API_KEY_SCOPES = frozenset(API_KEY_SCOPE_PERMISSIONS)


def permissions_for_api_key_scopes(scopes: list[str]) -> frozenset[str]:
    return frozenset(
        permission
        for scope in scopes
        for permission in API_KEY_SCOPE_PERMISSIONS.get(scope, frozenset())
    )
