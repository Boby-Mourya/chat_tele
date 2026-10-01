from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from northstar_api.billing_provider_config import StripeBillingSettings
from northstar_api.database import SessionFactory
from northstar_api.models import Tenant
from northstar_api.routers import billing as billing_router
from northstar_api.services.stripe_billing import (
    StripeBillingClient,
    StripeBillingError,
    decode_stripe_event,
    stripe_subscription_snapshot,
    verify_stripe_signature,
)
from northstar_api.services.subscriptions import ensure_tenant_subscription
from northstar_api.subscriptions import SubscriptionStatus, TenantSubscription


def _settings() -> StripeBillingSettings:
    return StripeBillingSettings(
        stripe_secret_key="sk_test_northstar",
        stripe_webhook_secret="whsec_northstar",
        stripe_price_professional="price_professional",
        stripe_price_business="price_business",
        stripe_checkout_success_url="https://app.example.com/settings?billing=success",
        stripe_checkout_cancel_url="https://app.example.com/settings?billing=cancelled",
        stripe_portal_return_url="https://app.example.com/settings",
    )


def _signature(body: bytes, timestamp: int, secret: str = "whsec_northstar") -> str:
    digest = hmac.new(
        secret.encode(),
        str(timestamp).encode() + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    return f"t={timestamp},v1={digest}"


async def _tenant_id(client: AsyncClient, auth_headers: dict[str, str]) -> UUID:
    response = await client.get("/api/v1/workspace", headers=auth_headers)
    assert response.status_code == 200, response.text
    return UUID(response.json()["tenantId"])


async def _snapshot(tenant_id: UUID) -> dict[str, Any]:
    async with SessionFactory() as session:
        tenant = await session.get(Tenant, tenant_id)
        assert tenant is not None
        subscription = await ensure_tenant_subscription(session, tenant=tenant)
        await session.commit()
        return {
            "plan": subscription.plan,
            "status": subscription.status,
            "provider": subscription.provider,
            "provider_customer_id": subscription.provider_customer_id,
            "provider_subscription_id": subscription.provider_subscription_id,
            "trial_ends_at": subscription.trial_ends_at,
            "current_period_start": subscription.current_period_start,
            "current_period_end": subscription.current_period_end,
            "cancel_at_period_end": subscription.cancel_at_period_end,
            "past_due_at": subscription.past_due_at,
            "suspended_at": subscription.suspended_at,
            "cancelled_at": subscription.cancelled_at,
        }


async def _restore(tenant_id: UUID, values: dict[str, Any]) -> None:
    async with SessionFactory() as session:
        tenant = await session.get(Tenant, tenant_id)
        subscription = await session.scalar(
            select(TenantSubscription).where(TenantSubscription.tenant_id == tenant_id)
        )
        assert tenant is not None and subscription is not None
        for field, value in values.items():
            setattr(subscription, field, value)
        tenant.plan = str(values["plan"])
        await session.commit()


def test_stripe_signature_verification_accepts_rotation_and_rejects_replay() -> None:
    body = b'{"type":"customer.subscription.updated"}'
    timestamp = 1_789_000_000
    valid = _signature(body, timestamp)
    digest = valid.split("v1=", 1)[1]
    rotated = f"t={timestamp},v1=not-the-right-signature,v1={digest}"

    assert verify_stripe_signature(
        body, rotated, "whsec_northstar", tolerance_seconds=300, now=timestamp + 10
    ) == timestamp
    with pytest.raises(StripeBillingError, match="outside the allowed window"):
        verify_stripe_signature(
            body, valid, "whsec_northstar", tolerance_seconds=300, now=timestamp + 301
        )
    with pytest.raises(StripeBillingError, match="signature is invalid"):
        verify_stripe_signature(
            body, f"t={timestamp},v1=bad", "whsec_northstar", now=timestamp
        )


def test_stripe_subscription_snapshot_is_price_mapped_and_fail_closed() -> None:
    payload = {
        "id": "sub_123",
        "customer": "cus_123",
        "status": "past_due",
        "cancel_at_period_end": True,
        "trial_end": None,
        "items": {
            "data": [
                {
                    "price": {"id": "price_business"},
                    "current_period_start": 1_789_000_000,
                    "current_period_end": 1_791_592_000,
                }
            ]
        },
    }
    snapshot = stripe_subscription_snapshot(payload, settings=_settings())
    assert snapshot.plan == "business"
    assert snapshot.status is SubscriptionStatus.PAST_DUE
    assert snapshot.provider_customer_id == "cus_123"
    assert snapshot.cancel_at_period_end is True
    assert snapshot.current_period_start == datetime.fromtimestamp(1_789_000_000, tz=UTC)

    payload["items"]["data"][0]["price"]["id"] = "price_untrusted"  # type: ignore[index]
    with pytest.raises(StripeBillingError, match="not mapped"):
        stripe_subscription_snapshot(payload, settings=_settings())


@pytest.mark.anyio
async def test_checkout_and_portal_use_hosted_stripe_request_shapes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, Any]] = []
    responses = [
        httpx.Response(200, json={"url": "https://checkout.stripe.com/c/pay/test"}),
        httpx.Response(200, json={"url": "https://billing.stripe.com/p/session/test"}),
    ]

    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
            captured.append({"method": method, "url": url, **kwargs})
            return responses.pop(0)

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    client = StripeBillingClient(_settings())
    checkout = await client.create_checkout_session(
        tenant_id=UUID("11111111-1111-1111-1111-111111111111"),
        plan="professional",
        customer_id=None,
        customer_email="owner@example.com",
    )
    portal = await client.create_portal_session(customer_id="cus_123")

    assert checkout.startswith("https://checkout.stripe.com/")
    assert portal.startswith("https://billing.stripe.com/")
    checkout_data = dict(captured[0]["data"])
    assert captured[0]["url"] == "https://api.stripe.com/v1/checkout/sessions"
    assert checkout_data["mode"] == "subscription"
    assert checkout_data["line_items[0][price]"] == "price_professional"
    assert checkout_data["client_reference_id"] == "11111111-1111-1111-1111-111111111111"
    assert checkout_data["subscription_data[metadata][tenant_id]"] == checkout_data["client_reference_id"]
    assert checkout_data["subscription_data[metadata][plan]"] == "professional"
    assert checkout_data["customer_email"] == "owner@example.com"
    assert captured[1]["url"] == "https://api.stripe.com/v1/billing_portal/sessions"
    assert dict(captured[1]["data"])["customer"] == "cus_123"


@pytest.mark.anyio
async def test_checkout_waits_for_signed_webhook_before_granting_paid_plan(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = await _tenant_id(client, auth_headers)
    original = await _snapshot(tenant_id)
    settings = _settings()

    async def create_checkout_session(**kwargs: Any) -> str:
        assert kwargs["tenant_id"] == tenant_id
        assert kwargs["plan"] == "professional"
        return "https://checkout.stripe.com/c/pay/test"

    monkeypatch.setattr(billing_router, "get_stripe_billing_settings", lambda: settings)
    monkeypatch.setattr(
        billing_router.stripe_billing_client,
        "create_checkout_session",
        create_checkout_session,
    )
    try:
        checkout = await client.post(
            "/api/v1/billing/checkout",
            headers=auth_headers,
            json={"plan": "professional"},
        )
        assert checkout.status_code == 200, checkout.text
        assert checkout.json()["url"].startswith("https://checkout.stripe.com/")

        before_webhook = await client.get("/api/v1/billing/subscription", headers=auth_headers)
        assert before_webhook.status_code == 200, before_webhook.text
        assert before_webhook.json()["plan"] == original["plan"]
        assert before_webhook.json()["provider"] == original["provider"]

        subscription_payload = {
            "id": "sub_northstar_123",
            "customer": "cus_northstar_123",
            "status": "active",
            "cancel_at_period_end": False,
            "metadata": {"tenant_id": str(tenant_id), "plan": "professional"},
            "items": {
                "data": [
                    {
                        "price": {"id": "price_professional"},
                        "current_period_start": 1_789_000_000,
                        "current_period_end": 1_791_592_000,
                    }
                ]
            },
        }

        async def retrieve_subscription(subscription_id: str) -> dict[str, Any]:
            assert subscription_id == "sub_northstar_123"
            return subscription_payload

        monkeypatch.setattr(
            billing_router.stripe_billing_client,
            "retrieve_subscription",
            retrieve_subscription,
        )
        # The delivered event is intentionally stale. The router must use only
        # its tenant/id routing data and refresh the current provider state.
        event = {
            "id": "evt_northstar_123",
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": "sub_northstar_123",
                    "status": "past_due",
                    "metadata": {"tenant_id": str(tenant_id)},
                }
            },
        }
        body = json.dumps(event, separators=(",", ":")).encode()
        timestamp = 1_789_000_100
        monkeypatch.setattr(
            "northstar_api.services.stripe_billing.time.time",
            lambda: timestamp,
        )
        webhook = await client.post(
            "/api/v1/billing/webhooks/stripe",
            content=body,
            headers={"Stripe-Signature": _signature(body, timestamp)},
        )
        assert webhook.status_code == 200, webhook.text
        assert webhook.json() == {"received": True, "processed": True}

        synced = await client.get("/api/v1/billing/subscription", headers=auth_headers)
        assert synced.status_code == 200, synced.text
        assert synced.json()["plan"] == "professional"
        assert synced.json()["status"] == "active"
        assert synced.json()["provider"] == "stripe"

        async with SessionFactory() as session:
            stored = await session.scalar(
                select(TenantSubscription).where(TenantSubscription.tenant_id == tenant_id)
            )
            assert stored is not None
            assert stored.provider_customer_id == "cus_northstar_123"
            assert stored.provider_subscription_id == "sub_northstar_123"
    finally:
        await _restore(tenant_id, original)


def test_decode_stripe_event_rejects_unsigned_payload() -> None:
    body = b'{"type":"customer.subscription.updated","data":{"object":{}}}'
    with pytest.raises(StripeBillingError):
        decode_stripe_event(body, "", settings=_settings(), now=1_789_000_000)
