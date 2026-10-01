from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select

from northstar_api.billing_provider_config import get_stripe_billing_settings
from northstar_api.database import set_tenant_context
from northstar_api.dependencies import DBSession, require_permissions
from northstar_api.entitlement_schemas import (
    EntitlementFeaturesOut,
    EntitlementLimitsOut,
    EntitlementUsageOut,
    TenantEntitlementsOut,
)
from northstar_api.models import Tenant, User
from northstar_api.security import Principal
from northstar_api.services.entitlements import entitlement_context
from northstar_api.services.stripe_billing import (
    StripeBillingError,
    decode_stripe_event,
    stripe_billing_client,
    stripe_subscription_snapshot,
)
from northstar_api.services.subscriptions import (
    SubscriptionError,
    cancel_tenant_subscription,
    ensure_tenant_subscription,
    normalize_plan,
    reactivate_tenant_subscription,
    set_subscription_state,
)
from northstar_api.subscription_schemas import (
    BillingCheckoutRequest,
    BillingRedirectOut,
    BillingWebhookOut,
    TenantSubscriptionCancellationRequest,
    TenantSubscriptionOut,
)
from northstar_api.subscriptions import TenantSubscription

router = APIRouter(prefix="/billing", tags=["billing"])
BillingViewPrincipal = Annotated[Principal, Depends(require_permissions("billing.view"))]
BillingManagePrincipal = Annotated[Principal, Depends(require_permissions("billing.manage"))]


def _out(subscription: TenantSubscription) -> TenantSubscriptionOut:
    return TenantSubscriptionOut(
        id=subscription.id,
        tenant_id=subscription.tenant_id,
        plan=subscription.plan,
        status=subscription.status,
        provider=subscription.provider,
        trial_ends_at=subscription.trial_ends_at,
        current_period_start=subscription.current_period_start,
        current_period_end=subscription.current_period_end,
        cancel_at_period_end=subscription.cancel_at_period_end,
        past_due_at=subscription.past_due_at,
        suspended_at=subscription.suspended_at,
        cancelled_at=subscription.cancelled_at,
        created_at=subscription.created_at,
        updated_at=subscription.updated_at,
    )


def _require_interactive_billing_session(principal: Principal) -> None:
    if principal.token_id.startswith("api_key:"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API keys cannot manage tenant billing or offboarding",
        )


def _stripe_tenant_id(value: dict[str, Any]) -> UUID | None:
    metadata = value.get("metadata")
    raw_tenant_id = metadata.get("tenant_id") if isinstance(metadata, dict) else None
    if not isinstance(raw_tenant_id, str):
        reference = value.get("client_reference_id")
        raw_tenant_id = reference if isinstance(reference, str) else None
    if not raw_tenant_id:
        return None
    try:
        return UUID(raw_tenant_id)
    except ValueError:
        return None


async def _sync_stripe_subscription(
    session: DBSession,
    *,
    tenant_id: UUID,
    stripe_subscription: dict[str, Any],
) -> None:
    config = get_stripe_billing_settings()
    payload_tenant_id = _stripe_tenant_id(stripe_subscription)
    if payload_tenant_id is not None and payload_tenant_id != tenant_id:
        raise StripeBillingError("Stripe subscription tenant metadata does not match the checkout tenant", 409)

    await set_tenant_context(session, tenant_id)
    tenant = await session.scalar(select(Tenant).where(Tenant.id == tenant_id))
    if tenant is None:
        raise StripeBillingError("Stripe subscription tenant no longer exists", 404)
    current = await session.scalar(
        select(TenantSubscription).where(TenantSubscription.tenant_id == tenant_id)
    )
    snapshot = stripe_subscription_snapshot(stripe_subscription, settings=config)
    if current is not None:
        if current.provider not in {None, "stripe"}:
            raise StripeBillingError("Tenant is already managed by a different billing provider", 409)
        if (
            current.provider_subscription_id
            and current.provider_subscription_id != snapshot.provider_subscription_id
        ):
            raise StripeBillingError("Stripe subscription does not match the tenant's managed subscription", 409)
        if (
            current.provider_customer_id
            and snapshot.provider_customer_id
            and current.provider_customer_id != snapshot.provider_customer_id
        ):
            raise StripeBillingError("Stripe customer does not match the tenant's managed customer", 409)

    await set_subscription_state(
        session,
        tenant_id=tenant_id,
        plan=snapshot.plan,
        status=snapshot.status,
        provider="stripe",
        provider_customer_id=snapshot.provider_customer_id,
        provider_subscription_id=snapshot.provider_subscription_id,
        trial_ends_at=snapshot.trial_ends_at,
        current_period_start=snapshot.current_period_start,
        current_period_end=snapshot.current_period_end,
        cancel_at_period_end=snapshot.cancel_at_period_end,
    )
    await session.commit()


@router.get("/subscription", response_model=TenantSubscriptionOut)
async def get_subscription(
    principal: BillingViewPrincipal,
    session: DBSession,
) -> TenantSubscriptionOut:
    tenant = await session.scalar(select(Tenant).where(Tenant.id == principal.tenant_id))
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    subscription = await ensure_tenant_subscription(session, tenant=tenant)
    await session.commit()
    await session.refresh(subscription)
    return _out(subscription)


@router.post("/checkout", response_model=BillingRedirectOut)
async def create_checkout(
    payload: BillingCheckoutRequest,
    principal: BillingManagePrincipal,
    session: DBSession,
) -> BillingRedirectOut:
    """Create a hosted Stripe Checkout session without pre-granting entitlements."""

    _require_interactive_billing_session(principal)
    tenant = await session.scalar(select(Tenant).where(Tenant.id == principal.tenant_id))
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    subscription = await ensure_tenant_subscription(session, tenant=tenant)
    try:
        plan = normalize_plan(payload.plan)
        config = get_stripe_billing_settings()
        if config.price_id_for_plan(plan) is None:
            raise StripeBillingError("This plan is not configured for Stripe checkout", 409)
        if subscription.provider and subscription.provider != "stripe":
            raise StripeBillingError("This subscription is managed by a different billing provider", 409)
        if subscription.provider == "stripe" and subscription.provider_subscription_id:
            raise StripeBillingError("Use the billing portal to manage an existing Stripe subscription", 409)
        user = await session.scalar(select(User).where(User.id == principal.user_id, User.is_active.is_(True)))
        url = await stripe_billing_client.create_checkout_session(
            tenant_id=principal.tenant_id,
            plan=plan,
            customer_id=(subscription.provider_customer_id if subscription.provider == "stripe" else None),
            customer_email=(user.email if user is not None else None),
        )
        # Deliberately do not update plan/status/provider here. Stripe's signed
        # subscription webhook is the source of truth for granting paid access.
        await session.rollback()
        return BillingRedirectOut(url=url)
    except SubscriptionError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None
    except StripeBillingError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None


@router.post("/portal", response_model=BillingRedirectOut)
async def create_billing_portal(
    principal: BillingManagePrincipal,
    session: DBSession,
) -> BillingRedirectOut:
    _require_interactive_billing_session(principal)
    subscription = await session.scalar(
        select(TenantSubscription).where(TenantSubscription.tenant_id == principal.tenant_id)
    )
    if (
        subscription is None
        or subscription.provider != "stripe"
        or not subscription.provider_customer_id
    ):
        raise HTTPException(status_code=409, detail="Stripe billing is not connected for this tenant")
    try:
        url = await stripe_billing_client.create_portal_session(
            customer_id=subscription.provider_customer_id
        )
        return BillingRedirectOut(url=url)
    except StripeBillingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None


@router.post("/webhooks/stripe", response_model=BillingWebhookOut, include_in_schema=False)
async def stripe_webhook(request: Request, session: DBSession) -> BillingWebhookOut:
    config = get_stripe_billing_settings()
    body = await request.body()
    if len(body) > config.stripe_webhook_max_bytes:
        raise HTTPException(status_code=413, detail="Stripe webhook payload is too large")
    signature = request.headers.get("Stripe-Signature", "")
    try:
        event = decode_stripe_event(body, signature, settings=config)
        event_type = event.get("type")
        event_data = event.get("data")
        stripe_object = event_data.get("object") if isinstance(event_data, dict) else None
        if not isinstance(stripe_object, dict):
            return BillingWebhookOut(processed=False)

        if event_type == "checkout.session.completed":
            tenant_id = _stripe_tenant_id(stripe_object)
            subscription_id = stripe_object.get("subscription")
            if tenant_id is None or not isinstance(subscription_id, str):
                return BillingWebhookOut(processed=False)
            stripe_subscription = await stripe_billing_client.retrieve_subscription(subscription_id)
            await _sync_stripe_subscription(
                session,
                tenant_id=tenant_id,
                stripe_subscription=stripe_subscription,
            )
            return BillingWebhookOut(processed=True)

        if event_type in {
            "customer.subscription.created",
            "customer.subscription.updated",
            "customer.subscription.deleted",
        }:
            tenant_id = _stripe_tenant_id(stripe_object)
            subscription_id = stripe_object.get("id")
            if tenant_id is None or not isinstance(subscription_id, str):
                return BillingWebhookOut(processed=False)
            # Webhook delivery order is not guaranteed. Re-read the current
            # subscription before applying state so a delayed old event cannot
            # regress a newer plan, payment or cancellation transition.
            stripe_subscription = await stripe_billing_client.retrieve_subscription(subscription_id)
            await _sync_stripe_subscription(
                session,
                tenant_id=tenant_id,
                stripe_subscription=stripe_subscription,
            )
            return BillingWebhookOut(processed=True)

        return BillingWebhookOut(processed=False)
    except StripeBillingError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None


@router.post("/cancel", response_model=TenantSubscriptionOut)
async def cancel_subscription(
    payload: TenantSubscriptionCancellationRequest,
    principal: BillingManagePrincipal,
    session: DBSession,
) -> TenantSubscriptionOut:
    _require_interactive_billing_session(principal)
    # Pydantic enforces the literal confirmation. Keeping the value in the
    # handler makes the destructive intent explicit at this boundary.
    assert payload.confirmation == "CANCEL"
    try:
        subscription = await cancel_tenant_subscription(
            session,
            tenant_id=principal.tenant_id,
        )
        await session.commit()
        await session.refresh(subscription)
        return _out(subscription)
    except SubscriptionError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None


@router.post("/reactivate", response_model=TenantSubscriptionOut)
async def reactivate_subscription(
    principal: BillingManagePrincipal,
    session: DBSession,
) -> TenantSubscriptionOut:
    _require_interactive_billing_session(principal)
    try:
        subscription = await reactivate_tenant_subscription(
            session,
            tenant_id=principal.tenant_id,
        )
        await session.commit()
        await session.refresh(subscription)
        return _out(subscription)
    except SubscriptionError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None


@router.get("/entitlements", response_model=TenantEntitlementsOut)
async def get_entitlements(
    principal: BillingViewPrincipal,
    session: DBSession,
) -> TenantEntitlementsOut:
    context = await entitlement_context(session, tenant_id=principal.tenant_id)
    policy = context.policy
    usage = context.usage
    return TenantEntitlementsOut(
        plan=context.subscription.plan,
        subscription_status=context.subscription.status,
        limits=EntitlementLimitsOut(
            workspaces=policy.workspace_limit,
            agents=policy.agent_limit,
            members=policy.member_limit,
            conversations_monthly=policy.conversation_limit_monthly,
            tokens_monthly=policy.token_limit_monthly,
            storage_bytes=policy.storage_limit_bytes,
        ),
        usage=EntitlementUsageOut(
            workspaces=usage.workspaces,
            agents=usage.agents,
            members=usage.members,
            pending_member_seats=usage.pending_member_seats,
            conversations_monthly=usage.conversations_monthly,
            tokens_monthly=usage.tokens_monthly,
            storage_bytes=usage.storage_bytes,
        ),
        features=EntitlementFeaturesOut(
            allowed_channels=sorted(policy.allowed_channels),
            crm=policy.crm_enabled,
            api=policy.api_enabled,
            white_label=policy.white_label_enabled,
        ),
    )
