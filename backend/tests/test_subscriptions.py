from __future__ import annotations

from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy import func, select

from northstar_api.database import SessionFactory
from northstar_api.models import Tenant, TenantMembership, User
from northstar_api.services.subscriptions import set_subscription_state
from northstar_api.subscriptions import SubscriptionStatus, TenantSubscription


async def test_billing_subscription_is_persisted_and_preserves_existing_tenant_plan(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    workspace_response = await client.get("/api/v1/workspace", headers=auth_headers)
    assert workspace_response.status_code == 200, workspace_response.text
    workspace = workspace_response.json()

    first = await client.get("/api/v1/billing/subscription", headers=auth_headers)
    assert first.status_code == 200, first.text
    payload = first.json()
    assert payload["tenantId"] == workspace["tenantId"]
    assert payload["plan"] == workspace["plan"]
    assert payload["status"] == "active"
    assert payload["provider"] is None
    assert payload["cancelAtPeriodEnd"] is False

    second = await client.get("/api/v1/billing/subscription", headers=auth_headers)
    assert second.status_code == 200, second.text
    assert second.json()["id"] == payload["id"]

    async with SessionFactory() as session:
        count = int(
            await session.scalar(
                select(func.count())
                .select_from(TenantSubscription)
                .where(TenantSubscription.tenant_id == UUID(workspace["tenantId"]))
            )
            or 0
        )
        assert count == 1
        tenant = await session.get(Tenant, UUID(workspace["tenantId"]))
        assert tenant is not None
        assert tenant.plan == workspace["plan"]


async def test_subscription_lifecycle_states_and_legacy_plan_stay_in_sync(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    workspace_response = await client.get("/api/v1/workspace", headers=auth_headers)
    assert workspace_response.status_code == 200, workspace_response.text
    workspace = workspace_response.json()
    tenant_id = UUID(workspace["tenantId"])
    original_plan = workspace["plan"]

    try:
        async with SessionFactory() as session:
            trial = await set_subscription_state(
                session,
                tenant_id=tenant_id,
                plan="professional",
                status=SubscriptionStatus.TRIAL,
            )
            await session.commit()
            assert trial.status is SubscriptionStatus.TRIAL
            assert trial.plan == "professional"

        response = await client.get("/api/v1/billing/subscription", headers=auth_headers)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "trial"
        assert response.json()["plan"] == "professional"

        async with SessionFactory() as session:
            past_due = await set_subscription_state(
                session,
                tenant_id=tenant_id,
                status=SubscriptionStatus.PAST_DUE,
            )
            await session.commit()
            assert past_due.past_due_at is not None

            suspended = await set_subscription_state(
                session,
                tenant_id=tenant_id,
                status=SubscriptionStatus.SUSPENDED,
            )
            await session.commit()
            assert suspended.suspended_at is not None

            cancelled = await set_subscription_state(
                session,
                tenant_id=tenant_id,
                status=SubscriptionStatus.CANCELLED,
            )
            await session.commit()
            assert cancelled.cancelled_at is not None

        cancelled_response = await client.get("/api/v1/billing/subscription", headers=auth_headers)
        assert cancelled_response.status_code == 200, cancelled_response.text
        assert cancelled_response.json()["status"] == "cancelled"

        workspace_after_plan_change = await client.get("/api/v1/workspace", headers=auth_headers)
        assert workspace_after_plan_change.status_code == 200, workspace_after_plan_change.text
        assert workspace_after_plan_change.json()["plan"] == "professional"
    finally:
        async with SessionFactory() as session:
            restored = await set_subscription_state(
                session,
                tenant_id=tenant_id,
                plan=original_plan,
                status=SubscriptionStatus.ACTIVE,
                cancel_at_period_end=False,
            )
            await session.commit()
            assert restored.status is SubscriptionStatus.ACTIVE
            assert restored.past_due_at is None
            assert restored.suspended_at is None
            assert restored.cancelled_at is None


async def test_self_service_signup_creates_starter_subscription_in_same_account_flow(
    client: AsyncClient,
) -> None:
    seed = uuid4().hex[:10]
    email = f"subscription-signup-{seed}@example.com"
    response = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Subscription Owner",
            "email": email,
            "password": "Subscription-Password-2026!",
            "organizationName": f"Subscription Organization {seed}",
            "termsAccepted": True,
            "privacyAccepted": True,
        },
    )
    assert response.status_code == 201, response.text

    async with SessionFactory() as session:
        user = await session.scalar(select(User).where(User.email == email))
        assert user is not None
        membership = await session.scalar(
            select(TenantMembership).where(TenantMembership.user_id == user.id)
        )
        assert membership is not None
        subscription = await session.scalar(
            select(TenantSubscription).where(
                TenantSubscription.tenant_id == membership.tenant_id
            )
        )
        assert subscription is not None
        assert subscription.plan == "starter"
        assert subscription.status is SubscriptionStatus.ACTIVE
        tenant = await session.get(Tenant, membership.tenant_id)
        assert tenant is not None
        assert tenant.plan == subscription.plan
