from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class EmailSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    email_delivery_mode: Literal["log", "smtp"] = "log"
    email_from_address: str = "no-reply@northstar.local"
    email_from_name: str = "Northstar"
    email_verification_frontend_url: str = "http://localhost:5173/verify-email"
    email_verification_ttl_hours: int = Field(default=24, ge=1, le=168)
    password_reset_frontend_url: str = "http://localhost:5173/reset-password"
    password_reset_ttl_minutes: int = Field(default=60, ge=10, le=1440)
    workspace_invitation_frontend_url: str = "http://localhost:5173/workspace-invitation"
    workspace_invitation_ttl_days: int = Field(default=7, ge=1, le=30)
    smtp_host: str = ""
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str = ""
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = True
    smtp_ssl: bool = False
    smtp_timeout_seconds: float = Field(default=10.0, gt=0, le=60)

    @model_validator(mode="after")
    def validate_smtp(self) -> EmailSettings:
        if self.smtp_ssl and self.smtp_starttls:
            raise ValueError("SMTP_SSL and SMTP_STARTTLS cannot both be enabled")
        if self.email_delivery_mode == "smtp" and not self.smtp_host.strip():
            raise ValueError("SMTP_HOST is required when EMAIL_DELIVERY_MODE=smtp")
        return self


@lru_cache(maxsize=1)
def get_email_settings() -> EmailSettings:
    return EmailSettings()
