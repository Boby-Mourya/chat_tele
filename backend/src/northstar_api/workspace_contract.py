"""Workspace input contracts and non-destructive legacy display fallbacks."""
from __future__ import annotations

import re
from typing import Any, Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, EmailStr, Field, ValidationError, field_validator

from northstar_api.branding_validation import decode_raster
from northstar_api.onboarding_contract import SetupContract


class WorkspacePreferences(SetupContract):
    timezone: str = Field(default="Asia/Calcutta", min_length=2, max_length=80)
    default_language: str = Field(default="English", min_length=2, max_length=60)
    date_format: Literal["DD/MM/YYYY", "MM/DD/YYYY", "YYYY-MM-DD"] = "DD/MM/YYYY"

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError("Choose a valid IANA timezone") from exc
        return value


class WorkspaceSecurityPolicy(SetupContract):
    sensitive_data_masking: bool = True
    security_contact: EmailStr | None = None


class WhiteLabelWrite(SetupContract):
    company_name: str = Field(default="Northstar AI", min_length=2, max_length=160)
    logo_data_url: str = Field(default="", max_length=500_000)
    favicon_data_url: str = Field(default="", max_length=500_000)
    app_icon_data_url: str = Field(default="", max_length=500_000)
    primary_color: str = "#0c0b0b"
    secondary_color: str = "#6b6b70"
    support_email: EmailStr | None = None
    support_url: str = Field(default="", max_length=2000)
    browser_title: str = Field(default="Northstar AI", min_length=1, max_length=120)
    branded_login: bool = False
    branded_dashboard: bool = True
    branded_widget: bool = False
    branded_emails: bool = False
    remove_platform_branding: bool = False
    # Kept on the legacy write contract for backwards-compatible clients.
    # Domain verification is still controlled by the dedicated domain lifecycle
    # endpoints; this field is never trusted as proof of ownership.
    custom_domain: str = Field(default="", max_length=253)
    dns_status: Literal[
        "not-configured", "pending", "dns_pending", "verifying", "verified",
        "certificate_pending", "active", "failed", "disabled",
    ] = "not-configured"

    @field_validator("primary_color", "secondary_color")
    @classmethod
    def valid_color(cls, value: str) -> str:
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            raise ValueError("must be a six-digit hex color")
        return value.lower()

    @field_validator("logo_data_url", "favicon_data_url", "app_icon_data_url")
    @classmethod
    def safe_image(cls, value: str) -> str:
        if value:
            decode_raster(value)
        return value

    @field_validator("support_url")
    @classmethod
    def safe_support_url(cls, value: str) -> str:
        if value:
            parsed = urlsplit(value)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("Support links must be HTTPS URLs without embedded credentials")
        return value


class WhiteLabelSettings(WhiteLabelWrite):
    # Legacy workspace responses expose the current domain lifecycle status;
    # writes still cannot advance verification beyond pending states.
    custom_domain: str = Field(default="", max_length=253)
    dns_status: Literal[
        "not-configured", "pending", "dns_pending", "verifying", "verified",
        "certificate_pending", "active", "failed", "disabled",
    ] = "not-configured"


def safe_legacy_read[ModelT: BaseModel](model: type[ModelT], raw: dict[str, Any], warnings: list[str]) -> ModelT:
    """Return safe values without changing the database or accepting invalid writes."""
    aliases = {field.alias or name: name for name, field in model.model_fields.items()}
    values = {key: value for key, value in raw.items() if key in aliases or key in model.model_fields}
    for _ in range(len(values) + 1):
        try:
            return model.model_validate(values)
        except ValidationError as exc:
            removed = False
            for error in exc.errors():
                key = str(error["loc"][0])
                name = aliases.get(key, key)
                alias = model.model_fields[name].alias if name in model.model_fields else key
                for candidate in {key, name, alias}:
                    if candidate is not None and candidate in values:
                        values.pop(candidate)
                        removed = True
                warnings.append(f"Stored {name} is invalid; using its safe default. Re-save to replace it.")
            if not removed:
                break
    return model.model_validate({})
