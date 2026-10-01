from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class StripeBillingSettings(BaseSettings):
    """Optional Stripe configuration for hosted subscription billing.

    The integration stays disabled until a secret key, webhook secret and at least
    one plan price are configured. Keeping these settings separate from the core
    application settings means provider-less/local billing continues to work
    unchanged in development and existing installations.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    stripe_secret_key: SecretStr | None = None
    stripe_webhook_secret: SecretStr | None = None
    stripe_price_starter: str = ""
    stripe_price_professional: str = ""
    stripe_price_business: str = ""
    stripe_price_enterprise: str = ""
    stripe_checkout_success_url: str = "http://localhost:3100/settings?billing=success"
    stripe_checkout_cancel_url: str = "http://localhost:3100/settings?billing=cancelled"
    stripe_portal_return_url: str = "http://localhost:3100/settings"
    stripe_api_base_url: str = "https://api.stripe.com"
    stripe_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    stripe_webhook_tolerance_seconds: int = Field(default=300, ge=30, le=900)
    stripe_webhook_max_bytes: int = Field(default=1_048_576, ge=1024, le=10_485_760)

    def secret_key(self) -> str:
        return self.stripe_secret_key.get_secret_value() if self.stripe_secret_key else ""

    def webhook_secret(self) -> str:
        return self.stripe_webhook_secret.get_secret_value() if self.stripe_webhook_secret else ""

    def price_id_for_plan(self, plan: str) -> str | None:
        normalized = plan.strip().lower().replace(" ", "_")
        values = {
            "starter": self.stripe_price_starter,
            "professional": self.stripe_price_professional,
            "business": self.stripe_price_business,
            "enterprise": self.stripe_price_enterprise,
        }
        value = values.get(normalized, "").strip()
        return value or None

    def plan_for_price_id(self, price_id: str | None) -> str | None:
        if not price_id:
            return None
        for plan in ("starter", "professional", "business", "enterprise"):
            if self.price_id_for_plan(plan) == price_id:
                return plan
        return None


@lru_cache(maxsize=1)
def get_stripe_billing_settings() -> StripeBillingSettings:
    return StripeBillingSettings()
