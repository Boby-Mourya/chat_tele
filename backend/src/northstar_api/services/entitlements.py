from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.config import get_settings
from northstar_api.entitlements import PlanEntitlement, entitlement_for_plan
from northstar_api.models import (
    Agent,
    Conversation,
    DocumentChunk,
    KnowledgeKind,
    KnowledgeSource,
    KnowledgeStatus,
    Message,
    Tenant,
    TenantMembership,
    User,
    Workspace,
    WorkspaceStatus,
)
from northstar_api.services.subscriptions import ensure_tenant_subscription
from northstar_api.subscriptions import SubscriptionStatus, TenantSubscription
from northstar_api.workspace_invitations import WorkspaceInvitation, WorkspaceInvitationStatus

ResourceName = Literal["workspaces", "agents", "members", "conversations", "tokens", "storage"]


class EntitlementError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 409, code: str = "entitlement_denied") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@dataclass(frozen=True, slots=True)
class EntitlementUsage:
    workspaces: int
    agents: int
    members: int
    pending_member_seats: int
    conversations_monthly: int
    tokens_monthly: int
    storage_bytes: int


@dataclass(frozen=True, slots=True)
class EntitlementContext:
    tenant: Tenant
    subscription: TenantSubscription
    policy: PlanEntitlement
    usage: EntitlementUsage


def _month_start(now: datetime | None = None) -> datetime:
    value = now or datetime.now(UTC)
    return datetime(value.year, value.month, 1, tzinfo=UTC)


def _stored_source_bytes(source: KnowledgeSource) -> int:
    content = getattr(source, "content", None)
    if content is not None:
        return len(str(content).encode("utf-8"))
    value = str(getattr(source, "size_label", "") or "").strip().upper()
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*(B|KB|MB|GB)", value)
    if match:
        amount = float(match.group(1))
        multiplier = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}[match.group(2)]
        return max(0, int(amount * multiplier))
    if (
        getattr(source, "kind", None) in {KnowledgeKind.URL, KnowledgeKind.SITEMAP}
        and getattr(source, "status", None) != KnowledgeStatus.FAILED
    ):
        # Remote sources have no authoritative byte size until extraction. Reserve
        # the configured maximum while they are pending so concurrent crawls cannot
        # all bypass the storage quota before chunks are written. Failed remote
        # sources retain no indexed/uploaded payload, so release that reservation.
        return get_settings().knowledge_max_extracted_characters * 4
    return 0


async def entitlement_usage(session: AsyncSession, *, tenant_id: UUID) -> EntitlementUsage:
    month_start = _month_start()
    workspaces = int(
        await session.scalar(
            select(func.count()).select_from(Workspace).where(
                Workspace.tenant_id == tenant_id,
                Workspace.status == WorkspaceStatus.ACTIVE,
            )
        )
        or 0
    )
    agents = int(
        await session.scalar(
            select(func.count()).select_from(Agent).where(
                Agent.tenant_id == tenant_id,
                Agent.deleted_at.is_(None),
            )
        )
        or 0
    )
    members = int(
        await session.scalar(
            select(func.count()).select_from(TenantMembership).where(
                TenantMembership.tenant_id == tenant_id,
            )
        )
        or 0
    )
    member_emails = set(
        await session.scalars(
            select(func.lower(User.email))
            .join(TenantMembership, TenantMembership.user_id == User.id)
            .where(TenantMembership.tenant_id == tenant_id)
        )
    )
    pending_emails = set(
        await session.scalars(
            select(func.lower(WorkspaceInvitation.email)).where(
                WorkspaceInvitation.tenant_id == tenant_id,
                WorkspaceInvitation.status == WorkspaceInvitationStatus.PENDING,
                WorkspaceInvitation.expires_at > datetime.now(UTC),
            )
        )
    )
    pending_member_seats = len(pending_emails - member_emails)
    conversations_monthly = int(
        await session.scalar(
            select(func.count()).select_from(Conversation).where(
                Conversation.tenant_id == tenant_id,
                Conversation.created_at >= month_start,
            )
        )
        or 0
    )
    tokens_monthly = int(
        await session.scalar(
            select(
                func.coalesce(func.sum(Message.prompt_tokens + Message.completion_tokens), 0)
            ).where(
                Message.tenant_id == tenant_id,
                Message.created_at >= month_start,
            )
        )
        or 0
    )
    chunk_contents = list(
        await session.scalars(
            select(DocumentChunk.content).where(DocumentChunk.tenant_id == tenant_id)
        )
    )
    pending_sources = list(
        await session.scalars(
            select(KnowledgeSource).where(
                KnowledgeSource.tenant_id == tenant_id,
                KnowledgeSource.chunk_count == 0,
            )
        )
    )
    # Ongoing storage represents indexed knowledge. Before a source is chunked,
    # its source content/known upload label (or remote extraction reservation) is
    # counted so concurrent ingestions do not temporarily disappear from usage.
    storage_bytes = sum(len(content.encode("utf-8")) for content in chunk_contents) + sum(
        _stored_source_bytes(source) for source in pending_sources
    )
    return EntitlementUsage(
        workspaces=workspaces,
        agents=agents,
        members=members,
        pending_member_seats=pending_member_seats,
        conversations_monthly=conversations_monthly,
        tokens_monthly=tokens_monthly,
        storage_bytes=storage_bytes,
    )


async def entitlement_context(session: AsyncSession, *, tenant_id: UUID) -> EntitlementContext:
    tenant = await session.scalar(select(Tenant).where(Tenant.id == tenant_id))
    if tenant is None:
        raise EntitlementError("Tenant not found", status_code=404, code="tenant_not_found")
    subscription = await ensure_tenant_subscription(session, tenant=tenant)
    return EntitlementContext(
        tenant=tenant,
        subscription=subscription,
        policy=entitlement_for_plan(subscription.plan),
        usage=await entitlement_usage(session, tenant_id=tenant_id),
    )


def _require_writable_subscription(context: EntitlementContext) -> None:
    if context.subscription.status == SubscriptionStatus.SUSPENDED:
        raise EntitlementError(
            "Subscription is suspended; restore billing access before creating new resources",
            status_code=403,
            code="subscription_suspended",
        )
    if context.subscription.status == SubscriptionStatus.CANCELLED:
        raise EntitlementError(
            "Subscription is cancelled; reactivate the account before creating new resources",
            status_code=403,
            code="subscription_cancelled",
        )


def _limit_and_usage(context: EntitlementContext, resource: ResourceName) -> tuple[int | None, int]:
    policy = context.policy
    usage = context.usage
    if resource == "workspaces":
        return policy.workspace_limit, usage.workspaces
    if resource == "agents":
        return policy.agent_limit, usage.agents
    if resource == "members":
        return policy.member_limit, usage.members + usage.pending_member_seats
    if resource == "conversations":
        return policy.conversation_limit_monthly, usage.conversations_monthly
    if resource == "tokens":
        return policy.token_limit_monthly, usage.tokens_monthly
    return policy.storage_limit_bytes, usage.storage_bytes


async def _serialize_capacity_check(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    resource: ResourceName,
) -> None:
    # Production runs PostgreSQL. A transaction-scoped advisory lock makes the
    # count-then-create decision deterministic across concurrent API/worker
    # processes. The route/worker uses this same session and releases the lock on
    # its normal commit/rollback. SQLite tests keep their existing lightweight path.
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
            {"scope": f"entitlement:{tenant_id}:{resource}"},
        )


async def require_capacity(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    resource: ResourceName,
    additional: int = 1,
) -> EntitlementContext:
    if additional < 0:
        raise ValueError("additional capacity must not be negative")
    await _serialize_capacity_check(session, tenant_id=tenant_id, resource=resource)
    context = await entitlement_context(session, tenant_id=tenant_id)
    _require_writable_subscription(context)
    limit, used = _limit_and_usage(context, resource)
    if limit is not None and used + additional > limit:
        label = resource.replace("_", " ")
        raise EntitlementError(
            f"{label.title()} plan limit reached ({used}/{limit}); upgrade the subscription to continue",
            status_code=409,
            code=f"{resource}_limit_reached",
        )
    return context


async def require_feature(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    feature: Literal["crm", "api", "white_label"],
) -> EntitlementContext:
    context = await entitlement_context(session, tenant_id=tenant_id)
    _require_writable_subscription(context)
    enabled = {
        "crm": context.policy.crm_enabled,
        "api": context.policy.api_enabled,
        "white_label": context.policy.white_label_enabled,
    }[feature]
    if not enabled:
        raise EntitlementError(
            f"{feature.replace('_', ' ').title()} is not available on the {context.subscription.plan} plan",
            status_code=403,
            code=f"{feature}_not_available",
        )
    return context


async def require_channel(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    provider: str,
) -> EntitlementContext:
    context = await entitlement_context(session, tenant_id=tenant_id)
    _require_writable_subscription(context)
    if provider not in context.policy.allowed_channels:
        raise EntitlementError(
            f"{provider.replace('_', ' ').title()} channel is not available on the {context.subscription.plan} plan",
            status_code=403,
            code="channel_not_available",
        )
    return context


def entitlement_http_detail(exc: EntitlementError) -> str:
    return str(exc)
