from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.lead_crm.audit_models import IntegrationAuditEvent
from northstar_api.lead_crm.channel_models import ChannelConnection
from northstar_api.lead_crm.domain import CRMConnectionStatus, CRMDeliveryStatus
from northstar_api.lead_crm.models import CRMConnection, CRMDelivery, IntegrationDeadLetter
from northstar_api.models import (
    Agent,
    Conversation,
    EventQuarantine,
    IngestionJob,
    JobStatus,
    Lead,
    OutboxEvent,
    Tenant,
    TenantMembership,
    User,
    Workspace,
    WorkspaceMembership,
)
from northstar_api.platform_admin_schemas import (
    PlatformAuditSummaryOut,
    PlatformOperationsOut,
    PlatformOverviewOut,
    PlatformSubscriptionBreakdownOut,
    PlatformTenantDetailOut,
    PlatformTenantListOut,
    PlatformTenantSummaryOut,
    PlatformTenantUserOut,
    PlatformWorkspaceSummaryOut,
)
from northstar_api.subscriptions import TenantSubscription

_CHANNEL_ISSUES = frozenset(
    {
        "degraded",
        "unhealthy",
        "error",
        "auth_required",
        "configuration_error",
        "rate_limited",
    }
)
_CRM_CONNECTION_ISSUES = frozenset(
    {
        CRMConnectionStatus.DEGRADED.value,
        CRMConnectionStatus.UNHEALTHY.value,
        CRMConnectionStatus.AUTH_REQUIRED.value,
        CRMConnectionStatus.RATE_LIMITED.value,
        CRMConnectionStatus.CONFIGURATION_ERROR.value,
    }
)
_CRM_DELIVERY_ISSUES = frozenset(
    {
        CRMDeliveryStatus.RETRYING.value,
        CRMDeliveryStatus.RATE_LIMITED.value,
        CRMDeliveryStatus.AUTH_REQUIRED.value,
        CRMDeliveryStatus.MAPPING_ERROR.value,
        CRMDeliveryStatus.FAILED.value,
        CRMDeliveryStatus.DEAD_LETTER.value,
    }
)


def _value(value: object, fallback: str = "unknown") -> str:
    resolved = getattr(value, "value", value)
    return str(resolved if resolved is not None else fallback)


async def _count(session: AsyncSession, model: type[Any], *conditions: Any) -> int:
    query = select(func.count()).select_from(model)
    if conditions:
        query = query.where(*conditions)
    return int(await session.scalar(query) or 0)


async def _group_count(
    session: AsyncSession,
    column: Any,
    ids: list[UUID],
    *conditions: Any,
) -> dict[UUID, int]:
    if not ids:
        return {}
    query = select(column, func.count()).where(column.in_(ids), *conditions).group_by(column)
    return {UUID(str(key)): int(value) for key, value in (await session.execute(query)).all()}


async def platform_overview(session: AsyncSession) -> PlatformOverviewOut:
    subscription_rows = (
        await session.execute(
            select(TenantSubscription.status, func.count()).group_by(TenantSubscription.status)
        )
    ).all()
    subscription_counts = {_value(status): int(count) for status, count in subscription_rows}
    subscriptions = PlatformSubscriptionBreakdownOut(
        trial=subscription_counts.get("trial", 0),
        active=subscription_counts.get("active", 0),
        past_due=subscription_counts.get("past_due", 0),
        suspended=subscription_counts.get("suspended", 0),
        cancelled=subscription_counts.get("cancelled", 0),
    )

    failed_jobs = await _count(session, IngestionJob, IngestionJob.status == JobStatus.FAILED)
    unpublished = await _count(session, OutboxEvent, OutboxEvent.published_at.is_(None))
    oldest_unpublished = await session.scalar(
        select(func.min(OutboxEvent.occurred_at)).where(OutboxEvent.published_at.is_(None))
    )
    quarantined = await _count(session, EventQuarantine)
    channel_issues = await _count(
        session,
        ChannelConnection,
        ChannelConnection.status.in_(_CHANNEL_ISSUES),
    )
    crm_connection_issues = await _count(
        session,
        CRMConnection,
        CRMConnection.status.in_(_CRM_CONNECTION_ISSUES),
    )
    crm_delivery_issues = await _count(
        session,
        CRMDelivery,
        CRMDelivery.status.in_(_CRM_DELIVERY_ISSUES),
    )
    dead_letters = await _count(
        session,
        IntegrationDeadLetter,
        IntegrationDeadLetter.status == "open",
    )
    critical_audit = await _count(
        session,
        IntegrationAuditEvent,
        IntegrationAuditEvent.created_at >= datetime.now(UTC) - timedelta(hours=24),
        or_(
            IntegrationAuditEvent.severity == "critical",
            IntegrationAuditEvent.outcome == "failure",
        ),
    )
    issue_total = (
        failed_jobs
        + unpublished
        + quarantined
        + channel_issues
        + crm_connection_issues
        + crm_delivery_issues
        + dead_letters
        + critical_audit
    )
    operations = PlatformOperationsOut(
        status="healthy" if issue_total == 0 else "degraded",
        failed_ingestion_jobs=failed_jobs,
        unpublished_outbox_events=unpublished,
        oldest_unpublished_event_at=oldest_unpublished,
        quarantined_events=quarantined,
        channel_issues=channel_issues,
        crm_connection_issues=crm_connection_issues,
        crm_delivery_issues=crm_delivery_issues,
        open_crm_dead_letters=dead_letters,
        critical_audit_events_24h=critical_audit,
    )
    return PlatformOverviewOut(
        tenants=await _count(session, Tenant),
        workspaces=await _count(session, Workspace),
        users=await _count(session, User, User.is_active.is_(True)),
        agents=await _count(session, Agent, Agent.deleted_at.is_(None)),
        conversations=await _count(session, Conversation),
        leads=await _count(session, Lead),
        subscriptions=subscriptions,
        operations=operations,
    )


async def _tenant_metric_maps(
    session: AsyncSession,
    tenant_ids: list[UUID],
) -> dict[str, dict[UUID, int]]:
    workspaces = await _group_count(session, Workspace.tenant_id, tenant_ids)
    members = await _group_count(session, TenantMembership.tenant_id, tenant_ids)
    agents = await _group_count(session, Agent.tenant_id, tenant_ids, Agent.deleted_at.is_(None))
    conversations = await _group_count(session, Conversation.tenant_id, tenant_ids)
    leads = await _group_count(session, Lead.tenant_id, tenant_ids)
    channel_issues = await _group_count(
        session,
        ChannelConnection.tenant_id,
        tenant_ids,
        ChannelConnection.status.in_(_CHANNEL_ISSUES),
    )
    crm_connections = await _group_count(
        session,
        CRMConnection.tenant_id,
        tenant_ids,
        CRMConnection.status.in_(_CRM_CONNECTION_ISSUES),
    )
    crm_deliveries = await _group_count(
        session,
        CRMDelivery.tenant_id,
        tenant_ids,
        CRMDelivery.status.in_(_CRM_DELIVERY_ISSUES),
    )
    crm_dead_letters = await _group_count(
        session,
        IntegrationDeadLetter.tenant_id,
        tenant_ids,
        IntegrationDeadLetter.status == "open",
    )
    return {
        "workspaces": workspaces,
        "members": members,
        "agents": agents,
        "conversations": conversations,
        "leads": leads,
        "channel_issues": channel_issues,
        "crm_issues": {
            tenant_id: crm_connections.get(tenant_id, 0)
            + crm_deliveries.get(tenant_id, 0)
            + crm_dead_letters.get(tenant_id, 0)
            for tenant_id in tenant_ids
        },
    }


def _tenant_summary(
    tenant: Tenant,
    subscription: TenantSubscription | None,
    metrics: dict[str, dict[UUID, int]],
) -> PlatformTenantSummaryOut:
    tenant_id = tenant.id
    return PlatformTenantSummaryOut(
        id=tenant_id,
        name=tenant.name,
        slug=tenant.slug,
        plan=subscription.plan if subscription else tenant.plan,
        subscription_status=_value(subscription.status, "active") if subscription else "active",
        workspace_count=metrics["workspaces"].get(tenant_id, 0),
        member_count=metrics["members"].get(tenant_id, 0),
        agent_count=metrics["agents"].get(tenant_id, 0),
        conversation_count=metrics["conversations"].get(tenant_id, 0),
        lead_count=metrics["leads"].get(tenant_id, 0),
        channel_issues=metrics["channel_issues"].get(tenant_id, 0),
        crm_issues=metrics["crm_issues"].get(tenant_id, 0),
        created_at=tenant.created_at,
    )


async def list_platform_tenants(
    session: AsyncSession,
    *,
    search: str | None,
    limit: int,
    offset: int,
) -> PlatformTenantListOut:
    filters: list[Any] = []
    normalized = (search or "").strip()
    if normalized:
        pattern = f"%{normalized}%"
        filters.append(or_(Tenant.name.ilike(pattern), Tenant.slug.ilike(pattern)))

    total_query = select(func.count()).select_from(Tenant)
    if filters:
        total_query = total_query.where(*filters)
    total = int(await session.scalar(total_query) or 0)

    query = (
        select(Tenant, TenantSubscription)
        .outerjoin(TenantSubscription, TenantSubscription.tenant_id == Tenant.id)
        .order_by(Tenant.created_at.desc(), Tenant.id)
        .limit(limit)
        .offset(offset)
    )
    if filters:
        query = query.where(*filters)
    rows = (await session.execute(query)).all()
    tenant_ids = [tenant.id for tenant, _ in rows]
    metrics = await _tenant_metric_maps(session, tenant_ids)
    return PlatformTenantListOut(
        items=[_tenant_summary(tenant, subscription, metrics) for tenant, subscription in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


async def get_platform_tenant(
    session: AsyncSession,
    *,
    tenant_id: UUID,
) -> PlatformTenantDetailOut | None:
    row = (
        await session.execute(
            select(Tenant, TenantSubscription)
            .outerjoin(TenantSubscription, TenantSubscription.tenant_id == Tenant.id)
            .where(Tenant.id == tenant_id)
        )
    ).first()
    if row is None:
        return None
    tenant, subscription = row
    metrics = await _tenant_metric_maps(session, [tenant_id])
    base = _tenant_summary(tenant, subscription, metrics)

    workspaces = list(
        await session.scalars(
            select(Workspace)
            .where(Workspace.tenant_id == tenant_id)
            .order_by(Workspace.created_at, Workspace.id)
        )
    )
    workspace_ids = [workspace.id for workspace in workspaces]
    workspace_members = await _group_count(session, WorkspaceMembership.workspace_id, workspace_ids)
    workspace_agents = await _group_count(
        session,
        Agent.workspace_id,
        workspace_ids,
        Agent.deleted_at.is_(None),
    )
    workspace_conversations = await _group_count(
        session,
        Conversation.workspace_id,
        workspace_ids,
    )
    workspace_leads = await _group_count(session, Lead.workspace_id, workspace_ids)
    workspace_out = [
        PlatformWorkspaceSummaryOut(
            id=workspace.id,
            name=workspace.name,
            slug=workspace.slug,
            status=_value(workspace.status),
            member_count=workspace_members.get(workspace.id, 0),
            agent_count=workspace_agents.get(workspace.id, 0),
            conversation_count=workspace_conversations.get(workspace.id, 0),
            lead_count=workspace_leads.get(workspace.id, 0),
            created_at=workspace.created_at,
        )
        for workspace in workspaces
    ]
    tenant_users = (
        await session.execute(
            select(User, TenantMembership)
            .join(TenantMembership, TenantMembership.user_id == User.id)
            .where(TenantMembership.tenant_id == tenant_id)
            .order_by(User.created_at, User.id)
        )
    ).all()
    users_out = [
        PlatformTenantUserOut(
            id=user.id,
            name=user.name,
            email=user.email,
            role=_value(membership.role),
            is_active=user.is_active,
            created_at=user.created_at,
        )
        for user, membership in tenant_users
    ]
    audit_values = list(
        await session.scalars(
            select(IntegrationAuditEvent)
            .where(IntegrationAuditEvent.tenant_id == tenant_id)
            .order_by(IntegrationAuditEvent.created_at.desc())
            .limit(20)
        )
    )
    recent_audit = [
        PlatformAuditSummaryOut(
            id=value.id,
            action=value.action,
            entity_type=value.entity_type,
            entity_id=value.entity_id,
            category=value.category,
            severity=value.severity,
            outcome=value.outcome,
            workspace_id=value.workspace_id,
            created_at=value.created_at,
        )
        for value in audit_values
    ]
    return PlatformTenantDetailOut(
        **base.model_dump(),
        provider=subscription.provider if subscription else None,
        current_period_end=subscription.current_period_end if subscription else None,
        cancel_at_period_end=subscription.cancel_at_period_end if subscription else False,
        workspaces=workspace_out,
        users=users_out,
        recent_audit=recent_audit,
    )
