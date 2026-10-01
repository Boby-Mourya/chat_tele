"""Persist Workspace settings without changing the legacy storage pipeline.

Every operation receives a Workspace already authorized and locked by its API
handler. The caller retains validation, audit, outbox and transaction ownership.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.models import (
    Workspace,
    WorkspaceDeveloperSettingsRecord,
    WorkspaceNotificationSettingsRecord,
    WorkspaceSecurityPolicyRecord,
)
from northstar_api.modules.workspace.contracts import (
    DeveloperSettings,
    GeneralSettings,
    NotificationSettings,
    SecuritySettings,
)
from northstar_api.modules.workspace.store import save_document, settings_document


def update_general_settings(workspace: Workspace, payload: GeneralSettings) -> dict[str, Any]:
    document = settings_document(workspace)
    before = document.general.model_dump(by_alias=True, mode="json")
    document.general = payload
    save_document(workspace, document)
    return before


def update_security_settings(workspace: Workspace, payload: SecuritySettings) -> dict[str, Any]:
    document = settings_document(workspace)
    before = document.security.model_dump(by_alias=True, mode="json")
    document.security = payload
    legacy = dict(workspace.settings_json or {})
    legacy["security"] = {
        "sensitiveDataMasking": payload.sensitive_data_masking,
        "securityContact": str(payload.security_contact) if payload.security_contact else None,
    }
    workspace.settings_json = legacy
    save_document(workspace, document)
    return before


async def sync_security_policy_record(
    session: AsyncSession,
    workspace: Workspace,
    payload: SecuritySettings,
) -> None:
    """Persist the security contract in a queryable normalized projection.

    The compatibility settings document remains the source for older clients;
    this projection gives enforcement and operations a tenant-scoped record
    without requiring JSON parsing on every request.
    """
    if not hasattr(session, "execute"):
        return
    record = await session.scalar(
        select(WorkspaceSecurityPolicyRecord).where(
            WorkspaceSecurityPolicyRecord.tenant_id == workspace.tenant_id,
            WorkspaceSecurityPolicyRecord.workspace_id == workspace.id,
        )
    )
    if record is None:
        record = WorkspaceSecurityPolicyRecord(
            tenant_id=workspace.tenant_id,
            workspace_id=workspace.id,
        )
        session.add(record)
    record.sensitive_data_masking = payload.sensitive_data_masking
    record.security_contact = str(payload.security_contact) if payload.security_contact else None
    record.mfa_enforcement = payload.mfa_enforcement
    record.session_timeout_minutes = payload.session_timeout_minutes
    record.password_min_length = payload.password_min_length
    record.ip_allowlist_json = list(payload.ip_allowlist)
    record.ip_denylist_json = list(payload.ip_denylist)
    record.trusted_domains_json = list(payload.trusted_domains)
    record.webhook_signing_required = payload.webhook_signing_required
    record.security_notifications = payload.security_notifications


async def sync_developer_settings_record(
    session: AsyncSession,
    workspace: Workspace,
    payload: DeveloperSettings,
) -> None:
    """Persist API/webhook controls in a queryable workspace projection."""
    if not hasattr(session, "execute"):
        return
    record = await session.scalar(
        select(WorkspaceDeveloperSettingsRecord).where(
            WorkspaceDeveloperSettingsRecord.tenant_id == workspace.tenant_id,
            WorkspaceDeveloperSettingsRecord.workspace_id == workspace.id,
        )
    )
    if record is None:
        record = WorkspaceDeveloperSettingsRecord(
            tenant_id=workspace.tenant_id,
            workspace_id=workspace.id,
        )
        session.add(record)
    record.sandbox_mode = payload.sandbox_mode
    record.webhook_signing_enabled = payload.webhook_signing_enabled
    record.webhook_events_json = list(payload.webhook_events)
    record.rate_limit_per_minute = payload.rate_limit_per_minute
    record.request_log_retention_days = payload.request_log_retention_days
    record.webhook_retry_limit = payload.webhook_retry_limit


async def sync_notification_settings_record(
    session: AsyncSession,
    workspace: Workspace,
    payload: NotificationSettings,
) -> None:
    """Persist notification routing preferences in a normalized projection."""
    if not hasattr(session, "execute"):
        return
    record = await session.scalar(
        select(WorkspaceNotificationSettingsRecord).where(
            WorkspaceNotificationSettingsRecord.tenant_id == workspace.tenant_id,
            WorkspaceNotificationSettingsRecord.workspace_id == workspace.id,
        )
    )
    if record is None:
        record = WorkspaceNotificationSettingsRecord(
            tenant_id=workspace.tenant_id,
            workspace_id=workspace.id,
        )
        session.add(record)
    record.member_changes = payload.member_changes
    record.security_alerts = payload.security_alerts
    record.billing_alerts = payload.billing_alerts
    record.channel_failures = payload.channel_failures
    record.integration_failures = payload.integration_failures
    record.weekly_digest = payload.weekly_digest
    record.recipients_json = [str(value) for value in payload.recipients]


def update_notification_settings(workspace: Workspace, payload: NotificationSettings) -> dict[str, Any]:
    document = settings_document(workspace)
    before = document.notifications.model_dump(by_alias=True, mode="json")
    document.notifications = payload
    save_document(workspace, document)
    return before


def update_developer_settings(workspace: Workspace, payload: DeveloperSettings) -> dict[str, Any]:
    document = settings_document(workspace)
    before = document.developer.model_dump(by_alias=True, mode="json")
    document.developer = payload
    save_document(workspace, document)
    return before
