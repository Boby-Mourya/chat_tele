from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy import select

from northstar_api.database import SessionFactory
from northstar_api.models import Tenant
from northstar_api.services.subscriptions import ensure_tenant_subscription
from northstar_api.subscriptions import SubscriptionStatus, TenantSubscription


async def _tenant_id(client: AsyncClient, auth_headers: dict[str, str]) -> UUID:
    response = await client.get('/api/v1/workspace', headers=auth_headers)
    assert response.status_code == 200, response.text
    return UUID(response.json()['tenantId'])


async def _snapshot(tenant_id: UUID) -> dict[str, Any]:
    async with SessionFactory() as session:
        tenant = await session.get(Tenant, tenant_id)
        assert tenant is not None
        subscription = await ensure_tenant_subscription(session, tenant=tenant)
        await session.commit()
        return {
            'plan': subscription.plan,
            'status': subscription.status,
            'provider': subscription.provider,
            'provider_customer_id': subscription.provider_customer_id,
            'provider_subscription_id': subscription.provider_subscription_id,
            'trial_ends_at': subscription.trial_ends_at,
            'current_period_start': subscription.current_period_start,
            'current_period_end': subscription.current_period_end,
            'cancel_at_period_end': subscription.cancel_at_period_end,
            'past_due_at': subscription.past_due_at,
            'suspended_at': subscription.suspended_at,
            'cancelled_at': subscription.cancelled_at,
        }


async def _set_subscription(tenant_id: UUID, **values: Any) -> None:
    async with SessionFactory() as session:
        subscription = await session.scalar(
            select(TenantSubscription).where(TenantSubscription.tenant_id == tenant_id)
        )
        assert subscription is not None
        for field, value in values.items():
            setattr(subscription, field, value)
        await session.commit()


async def _restore(tenant_id: UUID, snapshot: dict[str, Any]) -> None:
    async with SessionFactory() as session:
        tenant = await session.get(Tenant, tenant_id)
        subscription = await session.scalar(
            select(TenantSubscription).where(TenantSubscription.tenant_id == tenant_id)
        )
        assert tenant is not None and subscription is not None
        for field, value in snapshot.items():
            setattr(subscription, field, value)
        tenant.plan = str(snapshot['plan'])
        await session.commit()


async def test_manual_cancellation_preserves_access_to_existing_data_and_can_reactivate(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    tenant_id = await _tenant_id(client, auth_headers)
    snapshot = await _snapshot(tenant_id)
    try:
        await _set_subscription(
            tenant_id,
            status=SubscriptionStatus.ACTIVE,
            provider=None,
            provider_customer_id=None,
            provider_subscription_id=None,
            current_period_start=None,
            current_period_end=None,
            cancel_at_period_end=False,
            cancelled_at=None,
            past_due_at=None,
            suspended_at=None,
        )

        invalid = await client.post(
            '/api/v1/billing/cancel',
            headers=auth_headers,
            json={'confirmation': 'cancel'},
        )
        assert invalid.status_code == 422, invalid.text

        cancelled = await client.post(
            '/api/v1/billing/cancel',
            headers=auth_headers,
            json={'confirmation': 'CANCEL'},
        )
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()['status'] == 'cancelled'
        assert cancelled.json()['cancelAtPeriodEnd'] is False
        assert cancelled.json()['cancelledAt'] is not None

        # Soft offboarding never deletes or hides existing workspace/billing data.
        workspace = await client.get('/api/v1/workspace', headers=auth_headers)
        assert workspace.status_code == 200, workspace.text
        billing = await client.get('/api/v1/billing/subscription', headers=auth_headers)
        assert billing.status_code == 200, billing.text
        assert billing.json()['status'] == 'cancelled'

        # Existing entitlement guard now blocks a normally-allowed Starter API-key write.
        blocked = await client.post(
            '/api/v1/workspace/api-keys',
            headers=auth_headers,
            json={'name': f'Cancelled subscription key {uuid4().hex[:8]}'},
        )
        assert blocked.status_code == 403, blocked.text
        assert 'subscription is cancelled' in blocked.json()['error']['message'].lower()

        reactivated = await client.post('/api/v1/billing/reactivate', headers=auth_headers)
        assert reactivated.status_code == 200, reactivated.text
        assert reactivated.json()['status'] == 'active'
        assert reactivated.json()['cancelAtPeriodEnd'] is False
        assert reactivated.json()['cancelledAt'] is None
    finally:
        await _restore(tenant_id, snapshot)


async def test_period_end_cancellation_can_be_kept_and_auto_finalizes(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    tenant_id = await _tenant_id(client, auth_headers)
    snapshot = await _snapshot(tenant_id)
    try:
        future_end = datetime.now(UTC) + timedelta(days=20)
        await _set_subscription(
            tenant_id,
            status=SubscriptionStatus.ACTIVE,
            provider=None,
            current_period_end=future_end,
            cancel_at_period_end=False,
            cancelled_at=None,
        )

        scheduled = await client.post(
            '/api/v1/billing/cancel',
            headers=auth_headers,
            json={'confirmation': 'CANCEL'},
        )
        assert scheduled.status_code == 200, scheduled.text
        assert scheduled.json()['status'] == 'active'
        assert scheduled.json()['cancelAtPeriodEnd'] is True

        kept = await client.post('/api/v1/billing/reactivate', headers=auth_headers)
        assert kept.status_code == 200, kept.text
        assert kept.json()['status'] == 'active'
        assert kept.json()['cancelAtPeriodEnd'] is False

        scheduled_again = await client.post(
            '/api/v1/billing/cancel',
            headers=auth_headers,
            json={'confirmation': 'CANCEL'},
        )
        assert scheduled_again.status_code == 200, scheduled_again.text
        assert scheduled_again.json()['cancelAtPeriodEnd'] is True

        await _set_subscription(
            tenant_id,
            current_period_end=datetime.now(UTC) - timedelta(minutes=1),
        )

        # The existing entitlement boundary reconciles an expired cancellation
        # before allowing a new plan-gated resource, even without a billing page visit.
        blocked = await client.post(
            '/api/v1/workspace/api-keys',
            headers=auth_headers,
            json={'name': f'Expired subscription key {uuid4().hex[:8]}'},
        )
        assert blocked.status_code == 403, blocked.text
        assert 'subscription is cancelled' in blocked.json()['error']['message'].lower()

        finalized = await client.get('/api/v1/billing/subscription', headers=auth_headers)
        assert finalized.status_code == 200, finalized.text
        assert finalized.json()['status'] == 'cancelled'
        assert finalized.json()['cancelAtPeriodEnd'] is False

        reactivated = await client.post('/api/v1/billing/reactivate', headers=auth_headers)
        assert reactivated.status_code == 200, reactivated.text
        assert reactivated.json()['status'] == 'active'
    finally:
        await _restore(tenant_id, snapshot)


async def test_provider_backed_subscription_is_never_locally_faked_as_cancelled(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    tenant_id = await _tenant_id(client, auth_headers)
    snapshot = await _snapshot(tenant_id)
    try:
        await _set_subscription(
            tenant_id,
            status=SubscriptionStatus.ACTIVE,
            provider='stripe',
            current_period_end=datetime.now(UTC) + timedelta(days=15),
            cancel_at_period_end=False,
            cancelled_at=None,
        )
        refused = await client.post(
            '/api/v1/billing/cancel',
            headers=auth_headers,
            json={'confirmation': 'CANCEL'},
        )
        assert refused.status_code == 409, refused.text
        assert 'provider' in refused.json()['error']['message'].lower()

        state = await client.get('/api/v1/billing/subscription', headers=auth_headers)
        assert state.status_code == 200, state.text
        assert state.json()['status'] == 'active'
        assert state.json()['cancelAtPeriodEnd'] is False

        await _set_subscription(
            tenant_id,
            status=SubscriptionStatus.CANCELLED,
            cancel_at_period_end=False,
            cancelled_at=datetime.now(UTC),
        )
        reactivation = await client.post('/api/v1/billing/reactivate', headers=auth_headers)
        assert reactivation.status_code == 409, reactivation.text
        assert 'provider' in reactivation.json()['error']['message'].lower()
    finally:
        await _restore(tenant_id, snapshot)


async def test_api_key_cannot_manage_tenant_billing(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    created = await client.post(
        '/api/v1/workspace/api-keys',
        headers=auth_headers,
        json={'name': f'Billing boundary {uuid4().hex[:8]}'},
    )
    assert created.status_code == 201, created.text
    key_id = created.json()['id']
    secret = created.json()['secret']
    try:
        denied = await client.post(
            '/api/v1/billing/cancel',
            headers={'Authorization': f'Bearer {secret}'},
            json={'confirmation': 'CANCEL'},
        )
        assert denied.status_code == 403, denied.text
    finally:
        revoked = await client.delete(
            f'/api/v1/workspace/api-keys/{key_id}',
            headers=auth_headers,
        )
        assert revoked.status_code == 204, revoked.text
