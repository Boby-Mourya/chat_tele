from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import EmailStr, Field, field_validator

from northstar_api.access_policy import WORKSPACE_PERMISSIONS
from northstar_api.onboarding_contract import SetupContract
from northstar_api.workspace_contract import WhiteLabelWrite

_DAY_NAMES = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
_TIME_RANGE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d-(?:[01]\d|2[0-3]):[0-5]\d$")
_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


class BusinessHours(SetupContract):
    enabled: bool = False
    timezone: str = "Asia/Kolkata"
    schedule: dict[str, list[str]] = Field(default_factory=dict)

    @field_validator("schedule")
    @classmethod
    def validate_schedule(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        normalized: dict[str, list[str]] = {}
        for day, ranges in value.items():
            key = day.strip().lower()
            if key not in _DAY_NAMES:
                raise ValueError(f"Unsupported business-hours day: {day}")
            clean = list(dict.fromkeys(item.strip() for item in ranges if item.strip()))
            if len(clean) > 4 or any(not _TIME_RANGE.fullmatch(item) for item in clean):
                raise ValueError("Business-hour ranges must look like 09:00-17:30 and contain at most four ranges per day")
            normalized[key] = clean
        return normalized


class GeneralSettings(SetupContract):
    industry: str = Field(default="", max_length=120)
    country: str = Field(default="", max_length=80)
    time_format: Literal["12h", "24h"] = "24h"
    currency: str = Field(default="INR", min_length=3, max_length=3)
    week_start: Literal["monday", "sunday"] = "monday"
    description: str = Field(default="", max_length=1000)
    workspace_icon: str = Field(default="", max_length=500_000)
    business_hours: BusinessHours = Field(default_factory=BusinessHours)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized.isalpha():
            raise ValueError("Currency must be a three-letter code")
        return normalized


class SecuritySettings(SetupContract):
    sensitive_data_masking: bool = True
    security_contact: EmailStr | None = None
    mfa_enforcement: Literal["optional", "admins", "all"] = "optional"
    session_timeout_minutes: int = Field(default=480, ge=15, le=43200)
    password_min_length: int = Field(default=12, ge=8, le=128)
    ip_allowlist: list[str] = Field(default_factory=list, max_length=100)
    ip_denylist: list[str] = Field(default_factory=list, max_length=100)
    trusted_domains: list[str] = Field(default_factory=list, max_length=100)
    webhook_signing_required: bool = True
    security_notifications: bool = True


class NotificationSettings(SetupContract):
    member_changes: bool = True
    security_alerts: bool = True
    billing_alerts: bool = True
    channel_failures: bool = True
    integration_failures: bool = True
    weekly_digest: bool = False
    recipients: list[EmailStr] = Field(default_factory=list, max_length=50)


class DeveloperSettings(SetupContract):
    sandbox_mode: bool = False
    webhook_signing_enabled: bool = True
    webhook_events: list[str] = Field(default_factory=list, max_length=100)
    rate_limit_per_minute: int = Field(default=120, ge=10, le=100000)
    request_log_retention_days: int = Field(default=30, ge=1, le=365)
    webhook_retry_limit: int = Field(default=5, ge=0, le=20)


class ResourceScope(SetupContract):
    selected: dict[str, list[str]] = Field(default_factory=dict)
    conversation_scope: Literal["all", "assigned", "team"] = "all"


class CustomRole(SetupContract):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = Field(min_length=2, max_length=80)
    description: str = Field(default="", max_length=500)
    permissions: list[str] = Field(min_length=1, max_length=150)
    resources: ResourceScope = Field(default_factory=ResourceScope)

    @field_validator("permissions")
    @classmethod
    def registered_permissions(cls, value: list[str]) -> list[str]:
        selected = set(value)
        if not selected <= WORKSPACE_PERMISSIONS:
            raise ValueError("Only registered workspace permissions can be assigned")
        return sorted(selected)


class RolesSettings(SetupContract):
    custom_roles: list[CustomRole] = Field(default_factory=list, max_length=100)
    member_role_ids: dict[str, list[str]] = Field(default_factory=dict)


class WorkspaceTeam(SetupContract):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = Field(min_length=2, max_length=80)
    description: str = Field(default="", max_length=500)
    member_ids: list[str] = Field(default_factory=list, max_length=500)
    manager_ids: list[str] = Field(default_factory=list, max_length=100)
    role_ids: list[str] = Field(default_factory=list, max_length=50)
    queue_ids: list[str] = Field(default_factory=list, max_length=100)
    agent_ids: list[str] = Field(default_factory=list, max_length=500)
    channel_ids: list[str] = Field(default_factory=list, max_length=100)
    business_hours: BusinessHours = Field(default_factory=BusinessHours)
    escalation_rule: str = Field(default="", max_length=1000)


class TeamsSettings(SetupContract):
    teams: list[WorkspaceTeam] = Field(default_factory=list, max_length=100)


class DashboardWidget(SetupContract):
    id: str = Field(default_factory=lambda: str(uuid4()))
    type: str = Field(min_length=2, max_length=80)
    x: int = Field(default=0, ge=0, le=24)
    y: int = Field(default=0, ge=0, le=1000)
    width: int = Field(default=4, ge=1, le=24)
    height: int = Field(default=2, ge=1, le=24)
    visible: bool = True
    audience: list[str] = Field(default_factory=list, max_length=30)
    config: dict[str, Any] = Field(default_factory=dict)


class DashboardSettings(SetupContract):
    layout_version: int = Field(default=1, ge=1)
    landing_screen: str = Field(default="overview", max_length=80)
    widgets: list[DashboardWidget] = Field(default_factory=list, max_length=100)


class BrandAssets(SetupContract):
    compact_logo: str = Field(default="", max_length=500_000)
    dark_mode_logo: str = Field(default="", max_length=500_000)
    login_illustration: str = Field(default="", max_length=500_000)
    email_logo: str = Field(default="", max_length=500_000)
    widget_logo: str = Field(default="", max_length=500_000)


class BrandColors(SetupContract):
    primary_hover: str = "#27272a"
    accent: str = "#2563eb"
    background: str = "#ffffff"
    surface: str = "#ffffff"
    sidebar_background: str = "#0c0b0b"
    sidebar_text: str = "#ffffff"
    header: str = "#ffffff"
    text_primary: str = "#111827"
    text_secondary: str = "#6b7280"
    success: str = "#16a34a"
    warning: str = "#d97706"
    error: str = "#dc2626"
    border: str = "#e5e7eb"
    link: str = "#2563eb"

    @field_validator("*")
    @classmethod
    def valid_color(cls, value: str) -> str:
        if not _HEX_COLOR.fullmatch(value):
            raise ValueError("Brand colors must be six-digit hex values")
        return value.lower()


class BrandTypography(SetupContract):
    heading_font: str = Field(default="Inter", min_length=1, max_length=120)
    body_font: str = Field(default="Inter", min_length=1, max_length=120)
    base_font_size: int = Field(default=16, ge=12, le=24)
    heading_scale: float = Field(default=1.25, ge=1.0, le=2.0)
    normal_weight: int = Field(default=400, ge=100, le=900)
    medium_weight: int = Field(default=500, ge=100, le=900)
    bold_weight: int = Field(default=700, ge=100, le=900)


class DashboardAppearance(SetupContract):
    sidebar_logo: str = Field(default="", max_length=500_000)
    sidebar_style: Literal["solid", "soft", "minimal"] = "solid"
    sidebar_collapsed_default: bool = False
    header_style: Literal["solid", "transparent", "minimal"] = "solid"
    border_radius: int = Field(default=12, ge=0, le=32)
    card_appearance: Literal["flat", "bordered", "elevated"] = "bordered"
    density: Literal["compact", "comfortable", "spacious"] = "comfortable"
    mode: Literal["light", "dark", "system"] = "system"
    navigation_order: list[str] = Field(default_factory=list, max_length=100)
    navigation_hidden: list[str] = Field(default_factory=list, max_length=100)


class AuthBranding(SetupContract):
    login_logo: str = Field(default="", max_length=500_000)
    login_background: str = Field(default="", max_length=500_000)
    login_title: str = Field(default="", max_length=120)
    login_description: str = Field(default="", max_length=500)
    signup_title: str = Field(default="", max_length=120)
    forgot_password_title: str = Field(default="", max_length=120)
    reset_password_title: str = Field(default="", max_length=120)
    mfa_title: str = Field(default="", max_length=120)
    invitation_title: str = Field(default="", max_length=120)
    terms_url: str = Field(default="", max_length=2000)
    privacy_url: str = Field(default="", max_length=2000)
    support_url: str = Field(default="", max_length=2000)
    footer: str = Field(default="", max_length=500)


class EmailTemplate(SetupContract):
    subject: str = Field(default="", max_length=240)
    heading: str = Field(default="", max_length=240)
    body: str = Field(default="", max_length=8000)
    button_label: str = Field(default="", max_length=120)


def _default_email_templates() -> dict[str, EmailTemplate]:
    return {
        "invitation": EmailTemplate(subject="You're invited to {{company_name}}", heading="Join {{workspace_name}}", body="{{inviter_name}} invited you to join {{workspace_name}}.", button_label="Accept invitation"),
        "password_reset": EmailTemplate(subject="Reset your password", heading="Reset your password", body="Use the secure link below to reset your password.", button_label="Reset password"),
        "email_verification": EmailTemplate(subject="Verify your email", heading="Verify your email", body="Confirm your email address to continue.", button_label="Verify email"),
        "security_alert": EmailTemplate(subject="Security alert", heading="Security alert", body="A security event occurred in your workspace."),
        "billing_notification": EmailTemplate(subject="Billing update", heading="Billing update", body="There is an update to your workspace billing."),
        "conversation_notification": EmailTemplate(subject="Conversation update", heading="Conversation update", body="A conversation requires your attention."),
        "lead_notification": EmailTemplate(subject="Lead update", heading="Lead update", body="A lead was updated in your workspace."),
        "education_notification": EmailTemplate(subject="Education update", heading="Education update", body="There is an education update in your workspace."),
    }


class EmailBranding(SetupContract):
    logo: str = Field(default="", max_length=500_000)
    sender_name: str = Field(default="", max_length=160)
    reply_to: EmailStr | None = None
    footer: str = Field(default="", max_length=1000)
    enabled_templates: list[str] = Field(default_factory=lambda: list(_default_email_templates()))
    templates: dict[str, EmailTemplate] = Field(default_factory=_default_email_templates)


class WidgetBranding(SetupContract):
    launcher_icon: str = Field(default="", max_length=500_000)
    launcher_color: str = "#0c0b0b"
    position: Literal["bottom-left", "bottom-right"] = "bottom-right"
    greeting: str = Field(default="How can I help?", max_length=240)
    widget_logo: str = Field(default="", max_length=500_000)
    header: str = Field(default="", max_length=160)
    background: str = "#ffffff"
    user_message_color: str = "#0c0b0b"
    agent_message_color: str = "#f3f4f6"
    agent_avatar: str = Field(default="", max_length=500_000)
    bot_avatar: str = Field(default="", max_length=500_000)
    font: Literal["Inter", "DM Sans", "Manrope", "System UI"] = "Inter"
    privacy_url: str = Field(default="", max_length=2000)
    powered_by_label: str = Field(default="", max_length=120)
    business_hours: BusinessHours = Field(default_factory=BusinessHours)
    offline_message: str = Field(default="We are currently offline.", max_length=300)

    @field_validator("launcher_color", "background", "user_message_color", "agent_message_color")
    @classmethod
    def valid_widget_color(cls, value: str) -> str:
        if not _HEX_COLOR.fullmatch(value):
            raise ValueError("Widget colors must be six-digit hex values")
        return value.lower()


class ExtendedBranding(SetupContract):
    identity: WhiteLabelWrite = Field(default_factory=WhiteLabelWrite)
    assets: BrandAssets = Field(default_factory=BrandAssets)
    colors: BrandColors = Field(default_factory=BrandColors)
    typography: BrandTypography = Field(default_factory=BrandTypography)
    appearance: DashboardAppearance = Field(default_factory=DashboardAppearance)
    dashboard: DashboardSettings = Field(default_factory=DashboardSettings)
    authentication: AuthBranding = Field(default_factory=AuthBranding)
    email: EmailBranding = Field(default_factory=EmailBranding)
    widget: WidgetBranding = Field(default_factory=WidgetBranding)
    navigation: dict[str, Any] = Field(default_factory=dict)


class BrandVersion(SetupContract):
    version: int
    created_by: str
    published_at: datetime
    change_note: str = Field(default="", max_length=500)
    branding: ExtendedBranding


class DomainRecord(SetupContract):
    id: str = Field(default_factory=lambda: str(uuid4()))
    hostname: str = Field(min_length=4, max_length=253)
    status: Literal["pending", "dns_pending", "verifying", "verified", "certificate_pending", "active", "failed", "disabled"] = "dns_pending"
    verification_name: str
    verification_value: str
    failure_reason: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("hostname")
    @classmethod
    def normalized_hostname(cls, value: str) -> str:
        normalized = value.strip().lower().rstrip(".")
        if "://" in normalized or "/" in normalized or " " in normalized or "." not in normalized:
            raise ValueError("Enter a hostname such as portal.customer.com")
        return normalized


class DomainsSettings(SetupContract):
    domains: list[DomainRecord] = Field(default_factory=list, max_length=20)


class WorkspaceSettingsBundle(SetupContract):
    general: GeneralSettings = Field(default_factory=GeneralSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    notifications: NotificationSettings = Field(default_factory=NotificationSettings)
    developer: DeveloperSettings = Field(default_factory=DeveloperSettings)
    roles: RolesSettings = Field(default_factory=RolesSettings)
    teams: TeamsSettings = Field(default_factory=TeamsSettings)
    dashboard: DashboardSettings = Field(default_factory=DashboardSettings)
    branding_draft: ExtendedBranding = Field(default_factory=ExtendedBranding)
    branding_published: ExtendedBranding | None = None
    branding_versions: list[BrandVersion] = Field(default_factory=list, max_length=50)
    domains: DomainsSettings = Field(default_factory=DomainsSettings)


class BrandingSettingsView(SetupContract):
    branding_draft: ExtendedBranding
    branding_published: ExtendedBranding | None = None
    branding_versions: list[BrandVersion] = Field(default_factory=list, max_length=50)
    domains: DomainsSettings = Field(default_factory=DomainsSettings)


class DomainCreate(SetupContract):
    hostname: str = Field(min_length=4, max_length=253)


class PublishRequest(SetupContract):
    change_note: str = Field(default="", max_length=500)


class RollbackRequest(SetupContract):
    version: int = Field(ge=1)
    change_note: str = Field(default="Rollback", max_length=500)