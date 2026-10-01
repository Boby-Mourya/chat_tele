from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx

from northstar_api.billing_provider_config import StripeBillingSettings, get_stripe_billing_settings
from northstar_api.subscriptions import SubscriptionStatus


class StripeBillingError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class StripeSubscriptionSnapshot:
    provider_subscription_id: str
    provider_customer_id: str | None
    plan: str
    status: SubscriptionStatus
    trial_ends_at: datetime | None
    current_period_start: datetime | None
    current_period_end: datetime | None
    cancel_at_period_end: bool


def _unix_datetime(value: Any) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return datetime.fromtimestamp(value, tz=UTC)


def _first_price_id(subscription: dict[str, Any]) -> str | None:
    items = subscription.get("items")
    if not isinstance(items, dict):
        return None
    data = items.get("data")
    if not isinstance(data, list):
        return None
    for item in data:
        if not isinstance(item, dict):
            continue
        price = item.get("price")
        if isinstance(price, dict) and isinstance(price.get("id"), str):
            return price["id"]
    return None


def _item_period(subscription: dict[str, Any], field: str) -> datetime | None:
    direct = _unix_datetime(subscription.get(field))
    if direct is not None:
        return direct
    items = subscription.get("items")
    if not isinstance(items, dict):
        return None
    data = items.get("data")
    if not isinstance(data, list):
        return None
    values = [
        resolved
        for item in data
        if isinstance(item, dict)
        for resolved in [_unix_datetime(item.get(field))]
        if resolved is not None
    ]
    if not values:
        return None
    return min(values) if field.endswith("start") else max(values)


_STRIPE_STATUS: dict[str, SubscriptionStatus] = {
    "trialing": SubscriptionStatus.TRIAL,
    "active": SubscriptionStatus.ACTIVE,
    "past_due": SubscriptionStatus.PAST_DUE,
    "canceled": SubscriptionStatus.CANCELLED,
    "unpaid": SubscriptionStatus.SUSPENDED,
    "paused": SubscriptionStatus.SUSPENDED,
    "incomplete": SubscriptionStatus.SUSPENDED,
    "incomplete_expired": SubscriptionStatus.CANCELLED,
}


def stripe_subscription_snapshot(
    subscription: dict[str, Any],
    *,
    settings: StripeBillingSettings | None = None,
) -> StripeSubscriptionSnapshot:
    config = settings or get_stripe_billing_settings()
    subscription_id = subscription.get("id")
    if not isinstance(subscription_id, str) or not subscription_id.startswith("sub_"):
        raise StripeBillingError("Stripe subscription payload is missing a subscription id", 400)
    raw_status = subscription.get("status")
    if not isinstance(raw_status, str) or raw_status not in _STRIPE_STATUS:
        raise StripeBillingError("Stripe subscription payload has an unsupported status", 400)
    price_id = _first_price_id(subscription)
    plan = config.plan_for_price_id(price_id)
    if plan is None:
        metadata = subscription.get("metadata")
        metadata_plan = metadata.get("plan") if isinstance(metadata, dict) else None
        if isinstance(metadata_plan, str):
            candidate = metadata_plan.strip().lower().replace(" ", "_")
            configured_price = config.price_id_for_plan(candidate)
            if configured_price and (price_id is None or configured_price == price_id):
                plan = candidate
    if plan is None:
        raise StripeBillingError("Stripe subscription price is not mapped to a Northstar plan", 409)
    customer = subscription.get("customer")
    customer_id = customer if isinstance(customer, str) and customer.startswith("cus_") else None
    return StripeSubscriptionSnapshot(
        provider_subscription_id=subscription_id,
        provider_customer_id=customer_id,
        plan=plan,
        status=_STRIPE_STATUS[raw_status],
        trial_ends_at=_unix_datetime(subscription.get("trial_end")),
        current_period_start=_item_period(subscription, "current_period_start"),
        current_period_end=_item_period(subscription, "current_period_end"),
        cancel_at_period_end=bool(subscription.get("cancel_at_period_end", False)),
    )


def verify_stripe_signature(
    body: bytes,
    signature_header: str,
    webhook_secret: str,
    *,
    tolerance_seconds: int = 300,
    now: int | None = None,
) -> int:
    """Verify Stripe's signed raw request body and return its timestamp.

    Stripe can include multiple v1 signatures during secret rotation, so any
    constant-time matching v1 value is accepted. The timestamp tolerance blocks
    replay of otherwise valid old payloads.
    """

    if not webhook_secret:
        raise StripeBillingError("Stripe webhook secret is not configured", 503)
    timestamp: int | None = None
    signatures: list[str] = []
    for item in signature_header.split(","):
        key, separator, value = item.strip().partition("=")
        if not separator:
            continue
        if key == "t":
            try:
                timestamp = int(value)
            except ValueError:
                timestamp = None
        elif key == "v1" and value:
            signatures.append(value)
    if timestamp is None or not signatures:
        raise StripeBillingError("Stripe webhook signature is invalid", 400)
    resolved_now = int(time.time()) if now is None else now
    if abs(resolved_now - timestamp) > tolerance_seconds:
        raise StripeBillingError("Stripe webhook signature timestamp is outside the allowed window", 400)
    signed_payload = str(timestamp).encode("ascii") + b"." + body
    expected = hmac.new(webhook_secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
        raise StripeBillingError("Stripe webhook signature is invalid", 400)
    return timestamp


def decode_stripe_event(
    body: bytes,
    signature_header: str,
    *,
    settings: StripeBillingSettings | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    config = settings or get_stripe_billing_settings()
    verify_stripe_signature(
        body,
        signature_header,
        config.webhook_secret(),
        tolerance_seconds=config.stripe_webhook_tolerance_seconds,
        now=now,
    )
    try:
        event = json.loads(body)
    except json.JSONDecodeError as exc:
        raise StripeBillingError("Stripe webhook payload is not valid JSON", 400) from exc
    if not isinstance(event, dict) or not isinstance(event.get("type"), str):
        raise StripeBillingError("Stripe webhook payload is invalid", 400)
    return event


class StripeBillingClient:
    def __init__(self, settings: StripeBillingSettings | None = None) -> None:
        self.settings = settings or get_stripe_billing_settings()

    def _secret_key(self) -> str:
        secret = self.settings.secret_key().strip()
        if not secret:
            raise StripeBillingError("Stripe billing is not configured", 503)
        return secret

    async def _request(
        self,
        method: str,
        path: str,
        *,
        data: list[tuple[str, str]] | None = None,
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._secret_key()}"}
        url = f"{self.settings.stripe_api_base_url.rstrip('/')}{path}"
        try:
            async with httpx.AsyncClient(timeout=self.settings.stripe_timeout_seconds) as client:
                response = await client.request(method, url, headers=headers, data=data)
        except httpx.HTTPError as exc:
            raise StripeBillingError("Stripe billing service is temporarily unavailable", 503) from exc
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if response.status_code >= 400:
            message = None
            if isinstance(payload, dict):
                error = payload.get("error")
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message = error["message"]
            if response.status_code == 429 or response.status_code >= 500:
                raise StripeBillingError(message or "Stripe billing service is temporarily unavailable", 503)
            raise StripeBillingError(message or "Stripe billing request was rejected", 409)
        if not isinstance(payload, dict):
            raise StripeBillingError("Stripe billing returned an invalid response")
        return payload

    async def create_checkout_session(
        self,
        *,
        tenant_id: UUID,
        plan: str,
        customer_id: str | None,
        customer_email: str | None,
    ) -> str:
        normalized_plan = plan.strip().lower().replace(" ", "_")
        price_id = self.settings.price_id_for_plan(normalized_plan)
        if price_id is None:
            raise StripeBillingError("This plan is not configured for Stripe checkout", 409)
        data: list[tuple[str, str]] = [
            ("mode", "subscription"),
            ("success_url", self.settings.stripe_checkout_success_url),
            ("cancel_url", self.settings.stripe_checkout_cancel_url),
            ("client_reference_id", str(tenant_id)),
            ("line_items[0][price]", price_id),
            ("line_items[0][quantity]", "1"),
            ("metadata[tenant_id]", str(tenant_id)),
            ("metadata[plan]", normalized_plan),
            ("subscription_data[metadata][tenant_id]", str(tenant_id)),
            ("subscription_data[metadata][plan]", normalized_plan),
        ]
        if customer_id:
            data.append(("customer", customer_id))
        elif customer_email:
            data.append(("customer_email", customer_email))
        payload = await self._request("POST", "/v1/checkout/sessions", data=data)
        url = payload.get("url")
        if not isinstance(url, str) or not url.startswith("https://"):
            raise StripeBillingError("Stripe checkout did not return a secure hosted URL")
        return url

    async def create_portal_session(self, *, customer_id: str) -> str:
        payload = await self._request(
            "POST",
            "/v1/billing_portal/sessions",
            data=[
                ("customer", customer_id),
                ("return_url", self.settings.stripe_portal_return_url),
            ],
        )
        url = payload.get("url")
        if not isinstance(url, str) or not url.startswith("https://"):
            raise StripeBillingError("Stripe billing portal did not return a secure hosted URL")
        return url

    async def retrieve_subscription(self, subscription_id: str) -> dict[str, Any]:
        if not subscription_id.startswith("sub_"):
            raise StripeBillingError("Stripe subscription id is invalid", 400)
        return await self._request("GET", f"/v1/subscriptions/{subscription_id}")


stripe_billing_client = StripeBillingClient()
