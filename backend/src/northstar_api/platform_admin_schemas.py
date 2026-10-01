from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from northstar_api.schemas import APIModel


class PlatformAdminAccessOut(APIModel):
    authorized: bool = True
    email: str


class PlatformOperatorOut(APIModel):
    user_id: UUID
    name: str
    email: str
    role: str
    permissions: list[str] = Field(default_factory=list)
    is_active: bool
    created_at: datetime


class PlatformOperatorPatch(APIModel):
    role: str = Field(pattern=r"^(owner|operations|billing|support|auditor)$")
    permissions: list[str] = Field(default_factory=list, max_length=30)
    is_active: bool = True
    reason: str = Field(min_length=5, max_length=500)


class PlatformOperationsOut(APIModel):
    status: str
    failed_ingestion_jobs: int
    unpublished_outbox_events: int
    oldest_unpublished_event_at: datetime | None = None
    quarantined_events: int
    channel_issues: int
    crm_connection_issues: int
    crm_delivery_issues: int
    open_crm_dead_letters: int
    critical_audit_events_24h: int


class PlatformSubscriptionBreakdownOut(APIModel):
    trial: int = 0
    active: int = 0
    past_due: int = 0
    suspended: int = 0
    cancelled: int = 0


class PlatformOverviewOut(APIModel):
    tenants: int
    workspaces: int
    users: int
    agents: int
    conversations: int
    leads: int
    subscriptions: PlatformSubscriptionBreakdownOut
    operations: PlatformOperationsOut


class PlatformEntitlementOut(APIModel):
    plan: str
    workspace_limit: int | None = None
    agent_limit: int | None = None
    member_limit: int | None = None
    conversation_limit_monthly: int | None = None
    token_limit_monthly: int | None = None
    storage_limit_bytes: int | None = None
    allowed_channels: list[str] = Field(default_factory=list)
    crm_enabled: bool
    api_enabled: bool
    white_label_enabled: bool
    custom_domain_enabled: bool
    branded_email_enabled: bool
    remove_platform_mark_enabled: bool


class PlatformConfigurationOut(APIModel):
    app_env: str
    app_api_prefix: str
    background_dispatch_enabled: bool
    kafka_enabled: bool
    education_multi_course_enabled: bool
    require_nvidia: bool
    allow_deterministic_embeddings: bool
    platform_impersonation_ttl_minutes: int
    rate_limit_fail_open: bool
    retrieval_candidate_limit: int
    retrieval_context_limit: int
    knowledge_max_pdf_pages: int
    knowledge_max_chunks: int


class PlatformTenantSummaryOut(APIModel):
    id: UUID
    name: str
    slug: str
    plan: str
    subscription_status: str
    workspace_count: int
    member_count: int
    agent_count: int
    conversation_count: int
    lead_count: int
    channel_issues: int
    crm_issues: int
    created_at: datetime


class PlatformTenantListOut(APIModel):
    items: list[PlatformTenantSummaryOut]
    total: int
    limit: int
    offset: int


class PlatformWorkspaceSummaryOut(APIModel):
    id: UUID
    name: str
    slug: str
    status: str
    member_count: int
    agent_count: int
    conversation_count: int
    lead_count: int
    created_at: datetime


class PlatformTenantUserOut(APIModel):
    id: UUID
    name: str
    email: str
    role: str
    is_active: bool
    created_at: datetime


class PlatformAuditSummaryOut(APIModel):
    id: UUID
    action: str
    entity_type: str
    entity_id: str
    category: str
    severity: str
    outcome: str
    workspace_id: UUID | None = None
    created_at: datetime


class PlatformTenantDetailOut(PlatformTenantSummaryOut):
    provider: str | None = None
    current_period_end: datetime | None = None
    cancel_at_period_end: bool = False
    workspaces: list[PlatformWorkspaceSummaryOut] = Field(default_factory=list)
    users: list[PlatformTenantUserOut] = Field(default_factory=list)
    recent_audit: list[PlatformAuditSummaryOut] = Field(default_factory=list)


class PlatformTenantSubscriptionPatch(APIModel):
    """Audited, reason-required subscription override for platform support."""

    plan: str | None = Field(default=None, min_length=1, max_length=40)
    status: str | None = Field(default=None, pattern=r"^(trial|active|past_due|suspended|cancelled)$")
    reason: str = Field(min_length=5, max_length=500)


class PlatformTenantLifecyclePatch(APIModel):
    action: str = Field(pattern=r"^(suspend|reactivate)$")
    reason: str = Field(min_length=5, max_length=500)


class PlatformImpersonationRequest(APIModel):
    tenant_id: UUID
    workspace_id: UUID
    user_id: UUID
    reason: str = Field(min_length=5, max_length=500)


class PlatformImpersonationOut(APIModel):
    access_token: str
    expires_at: datetime
    tenant_id: UUID
    workspace_id: UUID
    user_id: UUID
    impersonation_id: str


class PlatformImpersonationEnd(APIModel):
    reason: str = Field(min_length=5, max_length=500)
