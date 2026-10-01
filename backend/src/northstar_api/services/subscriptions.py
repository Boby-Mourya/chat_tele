from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.models import Tenant
from northstar_api.subscriptions import SubscriptionStatus, TenantSubscription


class SubscriptionError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def normalize_plan(value: str) -> str:
    normalized = value.strip().lower().replace(" ", "_")
    if not normalized or len(normalized) > 40:
        raise SubscriptionError("Invalid subscription plan")
    return normalized


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def reconcile_subscription_lifecycle(
    subscription: TenantSubscription,
    *,
    now: datetime | None = None,
) -> bool:
    """Apply period-end cancellation without deleting any tenant data.

    The check is deliberately cheap and is called whenever the subscription is
    loaded through the service. That means a scheduled cancellation becomes
    effective before entitlement checks even if no background billing provider is
    connected. Existing data remains intact; the entitlement layer blocks only the
    already-guarded new-resource / plan-gated writes for cancelled subscriptions.
    """
    changed = False
    if subscription.status == SubscriptionStatus.CANCELLED:
        if subscription.cancel_at_period_end:
            subscription.cancel_at_period_end = False
            changed = True
        return changed

    if not subscription.cancel_at_period_end or subscription.current_period_end is None:
        return False

    resolved_now = now or datetime.now(UTC)
    period_end = _aware(subscription.current_period_end)
    if period_end > resolved_now:
        return False

    subscription.status = SubscriptionStatus.CANCELLED
    subscription.cancelled_at = subscription.cancelled_at or period_end
    subscription.cancel_at_period_end = False
    return True


async def ensure_tenant_subscription(
    session: AsyncSession,
    *,
    tenant: Tenant,
) -> TenantSubscription:
    subscription = await session.scalar(
        select(TenantSubscription).where(TenantSubscription.tenant_id == tenant.id)
    )
    if subscription is not None:
        reconcile_subscription_lifecycle(subscription)
        return subscription

    subscription = TenantSubscription(
        tenant_id=tenant.id,
        plan=normalize_plan(tenant.plan or "starter"),
        status=SubscriptionStatus.ACTIVE,
    )
    session.add(subscription)
    await session.flush()
    return subscription


async def create_subscription_for_tenant(
    session: AsyncSession,
    *,
    tenant: Tenant,
    plan: str | None = None,
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE,
) -> TenantSubscription:
    existing = await session.scalar(
        select(TenantSubscription).where(TenantSubscription.tenant_id == tenant.id)
    )
    if existing is not None:
        reconcile_subscription_lifecycle(existing)
        return existing
    normalized_plan = normalize_plan(plan or tenant.plan or "starter")
    tenant.plan = normalized_plan
    subscription = TenantSubscription(
        tenant_id=tenant.id,
        plan=normalized_plan,
        status=status,
    )
    session.add(subscription)
    await session.flush()
    return subscription


async def _locked_subscription(
    session: AsyncSession,
    *,
    tenant_id: UUID,
) -> tuple[Tenant, TenantSubscription]:
    tenant = await session.scalar(
        select(Tenant).where(Tenant.id == tenant_id).with_for_update()
    )
    if tenant is None:
        raise SubscriptionError("Tenant not found", 404)
    subscription = await session.scalar(
        select(TenantSubscription)
        .where(TenantSubscription.tenant_id == tenant_id)
        .with_for_update()
    )
    if subscription is None:
        subscription = await ensure_tenant_subscription(session, tenant=tenant)
    reconcile_subscription_lifecycle(subscription)
    return tenant, subscription


async def cancel_tenant_subscription(
    session: AsyncSession,
    *,
    tenant_id: UUID,
) -> TenantSubscription:
    """Schedule or apply safe soft-offboarding for a provider-less subscription.

    Provider-backed billing cannot be truthfully cancelled until a provider adapter
    can confirm the external cancellation. Reject that path instead of changing only
    local state while a customer might continue to be charged.
    """
    _, subscription = await _locked_subscription(session, tenant_id=tenant_id)
    if subscription.status == SubscriptionStatus.CANCELLED:
        return subscription
    if subscription.cancel_at_period_end:
        return subscription
    if subscription.provider:
        raise SubscriptionError(
            "Provider-backed subscription cancellation is not connected yet; use the billing provider workflow",
            409,
        )

    now = datetime.now(UTC)
    if (
        subscription.current_period_end is not None
        and _aware(subscription.current_period_end) > now
    ):
        subscription.cancel_at_period_end = True
    else:
        subscription.status = SubscriptionStatus.CANCELLED
        subscription.cancelled_at = now
        subscription.cancel_at_period_end = False
    await session.flush()
    return subscription


async def reactivate_tenant_subscription(
    session: AsyncSession,
    *,
    tenant_id: UUID,
) -> TenantSubscription:
    """Undo local cancellation without mutating or deleting tenant resources."""
    _, subscription = await _locked_subscription(session, tenant_id=tenant_id)
    needs_change = subscription.cancel_at_period_end or subscription.status == SubscriptionStatus.CANCELLED
    if not needs_change:
        return subscription
    if subscription.provider:
        raise SubscriptionError(
            "Provider-backed subscription reactivation is not connected yet; use the billing provider workflow",
            409,
        )

    subscription.cancel_at_period_end = False
    if subscription.status == SubscriptionStatus.CANCELLED:
        subscription.status = SubscriptionStatus.ACTIVE
        subscription.cancelled_at = None
        subscription.past_due_at = None
        subscription.suspended_at = None
    await session.flush()
    return subscription


async def set_subscription_state(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    plan: str | None = None,
    status: SubscriptionStatus | None = None,
    provider: str | None = None,
    provider_customer_id: str | None = None,
    provider_subscription_id: str | None = None,
    trial_ends_at: datetime | None = None,
    current_period_start: datetime | None = None,
    current_period_end: datetime | None = None,
    cancel_at_period_end: bool | None = None,
) -> TenantSubscription:
    tenant = await session.scalar(select(Tenant).where(Tenant.id == tenant_id))
    if tenant is None:
        raise SubscriptionError("Tenant not found", 404)
    subscription = await ensure_tenant_subscription(session, tenant=tenant)
    now = datetime.now(UTC)

    if plan is not None:
        normalized_plan = normalize_plan(plan)
        subscription.plan = normalized_plan
        tenant.plan = normalized_plan
    if provider is not None:
        subscription.provider = provider.strip().lower() or None
    if provider_customer_id is not None:
        subscription.provider_customer_id = provider_customer_id.strip() or None
    if provider_subscription_id is not None:
        subscription.provider_subscription_id = provider_subscription_id.strip() or None
    if trial_ends_at is not None:
        subscription.trial_ends_at = trial_ends_at
    if current_period_start is not None:
        subscription.current_period_start = current_period_start
    if current_period_end is not None:
        subscription.current_period_end = current_period_end
    if cancel_at_period_end is not None:
        subscription.cancel_at_period_end = cancel_at_period_end

    if status is not None:
        subscription.status = status
        if status == SubscriptionStatus.PAST_DUE:
            subscription.past_due_at = subscription.past_due_at or now
        elif status == SubscriptionStatus.SUSPENDED:
            subscription.suspended_at = subscription.suspended_at or now
        elif status == SubscriptionStatus.CANCELLED:
            subscription.cancelled_at = subscription.cancelled_at or now
            subscription.cancel_at_period_end = False
        elif status in {SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIAL}:
            subscription.past_due_at = None
            subscription.suspended_at = None
            subscription.cancelled_at = None

    await session.flush()
    return subscription
