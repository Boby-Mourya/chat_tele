from __future__ import annotations

from northstar_api.schemas import APIModel
from northstar_api.subscriptions import SubscriptionStatus


class EntitlementLimitsOut(APIModel):
    workspaces: int | None
    agents: int | None
    members: int | None
    conversations_monthly: int | None
    tokens_monthly: int | None
    storage_bytes: int | None


class EntitlementUsageOut(APIModel):
    workspaces: int
    agents: int
    members: int
    pending_member_seats: int
    conversations_monthly: int
    tokens_monthly: int
    storage_bytes: int


class EntitlementFeaturesOut(APIModel):
    allowed_channels: list[str]
    crm: bool
    api: bool
    white_label: bool


class TenantEntitlementsOut(APIModel):
    plan: str
    subscription_status: SubscriptionStatus
    limits: EntitlementLimitsOut
    usage: EntitlementUsageOut
    features: EntitlementFeaturesOut
