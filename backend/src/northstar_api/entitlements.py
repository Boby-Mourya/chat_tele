from __future__ import annotations

import json
import os
from dataclasses import dataclass

ALL_CHANNELS = frozenset({
    "whatsapp", "instagram", "facebook_messenger", "telegram", "widget", "api", "slack", "custom",
    "website", "facebook", "teams", "notion", "zapier",
})


@dataclass(frozen=True, slots=True)
class PlanEntitlement:
    workspace_limit: int | None
    agent_limit: int | None
    member_limit: int | None
    conversation_limit_monthly: int | None
    token_limit_monthly: int | None
    storage_limit_bytes: int | None
    allowed_channels: frozenset[str]
    crm_enabled: bool
    api_enabled: bool
    white_label_enabled: bool
    custom_domain_enabled: bool = False
    branded_email_enabled: bool = False
    remove_platform_mark_enabled: bool = False


PLAN_ENTITLEMENTS: dict[str, PlanEntitlement] = {
    "free": PlanEntitlement(
        workspace_limit=1, agent_limit=1, member_limit=1, conversation_limit_monthly=50,
        token_limit_monthly=10_000, storage_limit_bytes=10 * 1024**2,
        allowed_channels=frozenset({"website", "widget"}), crm_enabled=False,
        api_enabled=False, white_label_enabled=True,
    ),
    "starter": PlanEntitlement(
        workspace_limit=1, agent_limit=2, member_limit=3, conversation_limit_monthly=1_000,
        token_limit_monthly=500_000, storage_limit_bytes=1024**3,
        allowed_channels=frozenset({"website", "widget", "api", "telegram"}), crm_enabled=False,
        api_enabled=True, white_label_enabled=False,
    ),
    "professional": PlanEntitlement(
        workspace_limit=3, agent_limit=5, member_limit=10, conversation_limit_monthly=3_000,
        token_limit_monthly=2_000_000, storage_limit_bytes=5 * 1024**3,
        allowed_channels=frozenset({"website", "widget", "api", "whatsapp", "telegram", "slack"}),
        crm_enabled=True, api_enabled=True, white_label_enabled=True,
    ),
    "business": PlanEntitlement(
        workspace_limit=10, agent_limit=10, member_limit=20, conversation_limit_monthly=5_000,
        token_limit_monthly=5_000_000, storage_limit_bytes=20 * 1024**3, allowed_channels=ALL_CHANNELS,
        crm_enabled=True, api_enabled=True, white_label_enabled=True, custom_domain_enabled=True,
        branded_email_enabled=True, remove_platform_mark_enabled=True,
    ),
    "enterprise": PlanEntitlement(
        workspace_limit=None, agent_limit=None, member_limit=None, conversation_limit_monthly=None,
        token_limit_monthly=None, storage_limit_bytes=None, allowed_channels=ALL_CHANNELS,
        crm_enabled=True, api_enabled=True, white_label_enabled=True, custom_domain_enabled=True,
        branded_email_enabled=True, remove_platform_mark_enabled=True,
    ),
}
# Compatibility entitlement for tenants created by the original custom-plan
# contract. Keep this as a stable object so callers can use identity checks
# while all new plans remain in the explicit catalog above.
CUSTOM_UNLIMITED_ENTITLEMENT = PLAN_ENTITLEMENTS["enterprise"]
UNKNOWN_PLAN_ENTITLEMENT = PlanEntitlement(
    workspace_limit=0, agent_limit=0, member_limit=0, conversation_limit_monthly=0,
    token_limit_monthly=0, storage_limit_bytes=0, allowed_channels=frozenset(),
    crm_enabled=False, api_enabled=False, white_label_enabled=False,
)


def legacy_plan_aliases() -> dict[str, str]:
    """Operator-controlled, explicit legacy mappings; never a browser-supplied override."""
    raw = json.loads(os.environ.get("NORTHSTAR_LEGACY_PLAN_ALIASES", "{}"))
    if not isinstance(raw, dict):
        raise ValueError("NORTHSTAR_LEGACY_PLAN_ALIASES must be a JSON object")
    result: dict[str, str] = {}
    for source, target in raw.items():
        if not isinstance(source, str) or not isinstance(target, str):
            raise ValueError("Legacy plan mappings must contain strings")
        source, target = source.strip().lower(), target.strip().lower()
        if not source or source in PLAN_ENTITLEMENTS or target not in PLAN_ENTITLEMENTS:
            raise ValueError("Legacy mappings may only map unknown names to a known catalog plan")
        result[source] = target
    return result


def entitlement_for_plan(plan: str) -> PlanEntitlement:
    normalized = plan.strip().lower()
    if normalized == "legacy_custom_contract":
        return CUSTOM_UNLIMITED_ENTITLEMENT
    resolved = legacy_plan_aliases().get(normalized, normalized)
    return PLAN_ENTITLEMENTS.get(resolved, UNKNOWN_PLAN_ENTITLEMENT)
