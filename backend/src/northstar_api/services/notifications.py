from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.models import Lead, User, Workspace, WorkspaceMembership, WorkspaceRole
from northstar_api.modules.workspace.contracts import NotificationSettings, WorkspaceSettingsBundle
from northstar_api.notifications import Notification

_NOTIFICATION_ADMIN_ROLES = (WorkspaceRole.ADMIN, WorkspaceRole.MANAGER)


async def create_notification(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    recipient_user_id: UUID,
    title: str,
    body: str,
    dedupe_key: str,
    workspace_id: UUID | None = None,
    category: str = "system",
    severity: str = "info",
    action_url: str | None = None,
    action_label: str | None = None,
    source_event_id: UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> Notification:
    normalized_dedupe_key = dedupe_key.strip()[:220]
    if not normalized_dedupe_key:
        raise ValueError("notification dedupe_key must not be empty")
    existing = await session.scalar(
        select(Notification).where(
            Notification.tenant_id == tenant_id,
            Notification.recipient_user_id == recipient_user_id,
            Notification.dedupe_key == normalized_dedupe_key,
        )
    )
    if existing is not None:
        return existing

    value = Notification(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        recipient_user_id=recipient_user_id,
        category=category[:40],
        severity=severity[:20],
        title=title[:180],
        body=body[:1000],
        action_url=action_url[:500] if action_url else None,
        action_label=action_label[:120] if action_label else None,
        dedupe_key=normalized_dedupe_key,
        source_event_id=source_event_id,
        metadata_json=metadata or {},
    )
    try:
        async with session.begin_nested():
            session.add(value)
            await session.flush()
        return value
    except IntegrityError:
        existing = await session.scalar(
            select(Notification).where(
                Notification.tenant_id == tenant_id,
                Notification.recipient_user_id == recipient_user_id,
                Notification.dedupe_key == normalized_dedupe_key,
            )
        )
        if existing is None:
            raise
        return existing


async def list_notifications(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    recipient_user_id: UUID,
    workspace_id: UUID,
    unread_only: bool = False,
    limit: int = 50,
) -> list[Notification]:
    query = select(Notification).where(
        Notification.tenant_id == tenant_id,
        Notification.recipient_user_id == recipient_user_id,
        Notification.archived_at.is_(None),
        or_(
            Notification.workspace_id == workspace_id,
            Notification.workspace_id.is_(None),
        ),
    )
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    return list(
        await session.scalars(
            query.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit)
        )
    )


async def unread_notification_count(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    recipient_user_id: UUID,
    workspace_id: UUID,
) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.tenant_id == tenant_id,
                Notification.recipient_user_id == recipient_user_id,
                Notification.archived_at.is_(None),
                Notification.read_at.is_(None),
                or_(
                    Notification.workspace_id == workspace_id,
                    Notification.workspace_id.is_(None),
                ),
            )
        )
        or 0
    )


async def mark_notification_read(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    recipient_user_id: UUID,
    workspace_id: UUID,
    notification_id: UUID,
) -> Notification | None:
    value = await session.scalar(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.tenant_id == tenant_id,
            Notification.recipient_user_id == recipient_user_id,
            Notification.archived_at.is_(None),
            or_(
                Notification.workspace_id == workspace_id,
                Notification.workspace_id.is_(None),
            ),
        )
    )
    if value is None:
        return None
    if value.read_at is None:
        value.read_at = datetime.now(UTC)
        await session.flush()
    return value


async def mark_all_notifications_read(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    recipient_user_id: UUID,
    workspace_id: UUID,
) -> int:
    result = await session.execute(
        update(Notification)
        .where(
            Notification.tenant_id == tenant_id,
            Notification.recipient_user_id == recipient_user_id,
            Notification.archived_at.is_(None),
            Notification.read_at.is_(None),
            or_(
                Notification.workspace_id == workspace_id,
                Notification.workspace_id.is_(None),
            ),
        )
        .values(read_at=datetime.now(UTC))
    )
    return int(result.rowcount or 0)


def _notification_settings(workspace: Workspace) -> NotificationSettings:
    raw = dict(workspace.settings_json or {}).get("workspaceSettingsV2", {})
    try:
        return WorkspaceSettingsBundle.model_validate(raw).notifications
    except (TypeError, ValueError):
        return NotificationSettings()


def _category_enabled(settings: NotificationSettings, category: str) -> bool:
    normalized = category.strip().lower()
    if normalized in {"security", "authentication"}:
        return settings.security_alerts
    if normalized in {"billing", "subscription", "usage"}:
        return settings.billing_alerts
    if normalized in {"channel", "channels", "delivery"}:
        return settings.channel_failures
    if normalized in {"integration", "integrations", "crm"}:
        return settings.integration_failures
    if normalized in {"member", "members", "workspace"}:
        return settings.member_changes
    return True


async def _workspace_notification_recipients(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    settings: NotificationSettings,
) -> list[UUID]:
    query = (
        select(WorkspaceMembership.user_id)
        .join(User, User.id == WorkspaceMembership.user_id)
        .where(
            WorkspaceMembership.tenant_id == tenant_id,
            WorkspaceMembership.workspace_id == workspace_id,
            User.is_active.is_(True),
        )
    )
    if settings.recipients:
        recipients = {str(value).strip().lower() for value in settings.recipients}
        query = query.where(func.lower(User.email).in_(recipients))
    else:
        query = query.where(WorkspaceMembership.role.in_(_NOTIFICATION_ADMIN_ROLES))
    return list(await session.scalars(query.distinct()))


async def notify_workspace_admins(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    title: str,
    body: str,
    dedupe_key: str,
    category: str,
    severity: str = "info",
    action_url: str | None = None,
    action_label: str | None = None,
    source_event_id: UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> int:
    workspace = await session.scalar(
        select(Workspace).where(
            Workspace.id == workspace_id,
            Workspace.tenant_id == tenant_id,
        )
    )
    if workspace is None:
        return 0
    settings = _notification_settings(workspace)
    if not _category_enabled(settings, category):
        return 0
    recipients = await _workspace_notification_recipients(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        settings=settings,
    )
    for user_id in recipients:
        await create_notification(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            recipient_user_id=user_id,
            title=title,
            body=body,
            dedupe_key=dedupe_key,
            category=category,
            severity=severity,
            action_url=action_url,
            action_label=action_label,
            source_event_id=source_event_id,
            metadata=metadata,
        )
    return len(recipients)


def _uuid(value: object) -> UUID | None:
    try:
        return UUID(str(value)) if value else None
    except (TypeError, ValueError):
        return None


async def project_notification_event(
    session: AsyncSession,
    *,
    event_id: UUID,
    event_type: str,
    tenant_id: UUID,
    payload: dict[str, Any],
) -> int:
    """Project selected existing domain events into human in-app notifications."""
    workspace_id = _uuid(payload.get("workspaceId"))
    metadata: dict[str, Any] = {"eventType": event_type}

    if event_type == "lead.created.v1":
        if workspace_id is None:
            return 0
        lead_id = _uuid(payload.get("leadId"))
        if lead_id:
            metadata["leadId"] = str(lead_id)
        return await notify_workspace_admins(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            title="New lead captured",
            body="A conversation was resolved into a new lead in this workspace.",
            dedupe_key=f"event:{event_id}",
            category="lead",
            action_url="/leads",
            action_label="View leads",
            source_event_id=event_id,
            metadata=metadata,
        )

    if event_type == "lead.crm.delivery.failed.v1":
        lead_id = _uuid(payload.get("leadId"))
        if lead_id is None:
            return 0
        if workspace_id is None:
            workspace_id = await session.scalar(
                select(Lead.workspace_id).where(
                    Lead.id == lead_id,
                    Lead.tenant_id == tenant_id,
                )
            )
        if workspace_id is None:
            return 0
        provider = str(payload.get("provider") or "CRM")[:80]
        error_code = str(payload.get("errorCode") or "delivery_failed")[:120]
        metadata.update({"leadId": str(lead_id), "provider": provider, "errorCode": error_code})
        return await notify_workspace_admins(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            title="CRM sync needs attention",
            body=f"A {provider} lead delivery failed and may require review or retry.",
            dedupe_key=f"event:{event_id}",
            category="crm",
            severity="warning",
            action_url="/leads",
            action_label="Review CRM status",
            source_event_id=event_id,
            metadata=metadata,
        )

    if event_type == "education.conversation.resolution.context_missing.v1":
        if workspace_id is None:
            return 0
        conversation_id = _uuid(payload.get("conversationId"))
        if conversation_id:
            metadata["conversationId"] = str(conversation_id)
        return await notify_workspace_admins(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            title="Education resolution needs review",
            body="An Education conversation was resolved without an authorization context.",
            dedupe_key=f"event:{event_id}",
            category="education",
            severity="warning",
            action_url="/conversations",
            action_label="Review conversation",
            source_event_id=event_id,
            metadata=metadata,
        )

    return 0
