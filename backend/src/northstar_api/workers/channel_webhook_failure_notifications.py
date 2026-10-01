from __future__ import annotations

from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from northstar_api.database import set_tenant_context
from northstar_api.lead_crm.channel_models import ChannelConnection
from northstar_api.lead_crm.channel_scope import WorkspaceChannelConnection
from northstar_api.lead_crm.models import RawWebhookEvent
from northstar_api.notifications import Notification
from northstar_api.services.notifications import notify_workspace_admins

logger = structlog.get_logger(__name__)

FAILED_WEBHOOK_BATCH_SIZE = 100
FAILED_WEBHOOK_RECOVERY_SCAN_SIZE = 500
_FAILED_WEBHOOK_INCIDENT_PREFIX = "channel-webhook-failed:"
_FAILED_WEBHOOK_RECOVERY_PREFIX = "channel-webhook-failed-recovery:"
_FAILED_WEBHOOK_RECOVERY_STATUSES = frozenset({"processed", "ignored", "rejected"})


async def failed_webhook_events(
    session: AsyncSession,
) -> list[tuple[UUID, UUID, UUID]]:
    """Return a bounded batch of bound failed raw events not already alerted."""

    bound_connection_ids = list(
        await session.scalars(select(WorkspaceChannelConnection.connection_id).distinct())
    )
    if not bound_connection_ids:
        return []

    alerted_event_ids = select(Notification.source_event_id).where(
        Notification.category == "channel",
        Notification.source_event_id.is_not(None),
        Notification.dedupe_key.like(f"{_FAILED_WEBHOOK_INCIDENT_PREFIX}%"),
    )
    rows = list(
        await session.execute(
            select(
                RawWebhookEvent.id,
                RawWebhookEvent.tenant_id,
                RawWebhookEvent.connection_key,
            )
            .where(
                RawWebhookEvent.processing_status == "failed",
                RawWebhookEvent.connection_key.in_([str(value) for value in bound_connection_ids]),
                ~RawWebhookEvent.id.in_(alerted_event_ids),
            )
            .order_by(RawWebhookEvent.received_at, RawWebhookEvent.id)
            .limit(FAILED_WEBHOOK_BATCH_SIZE)
        )
    )

    values: list[tuple[UUID, UUID, UUID]] = []
    for raw_event_id, tenant_id, connection_key in rows:
        try:
            connection_id = UUID(str(connection_key))
        except (TypeError, ValueError):
            continue
        values.append((raw_event_id, tenant_id, connection_id))
    return values


async def _notify_failed_webhook_event(
    factory: async_sessionmaker[AsyncSession],
    *,
    raw_event_id: UUID,
    tenant_id: UUID,
    connection_id: UUID,
) -> int:
    async with factory() as session:
        await set_tenant_context(session, tenant_id)
        raw = await session.scalar(
            select(RawWebhookEvent).where(
                RawWebhookEvent.id == raw_event_id,
                RawWebhookEvent.tenant_id == tenant_id,
                RawWebhookEvent.connection_key == str(connection_id),
                RawWebhookEvent.processing_status == "failed",
            )
        )
        if raw is None:
            return 0

        scoped = (
            await session.execute(
                select(WorkspaceChannelConnection.workspace_id, ChannelConnection.name)
                .join(
                    ChannelConnection,
                    ChannelConnection.id == WorkspaceChannelConnection.connection_id,
                )
                .where(
                    WorkspaceChannelConnection.tenant_id == tenant_id,
                    WorkspaceChannelConnection.connection_id == connection_id,
                    ChannelConnection.tenant_id == tenant_id,
                )
            )
        ).first()
        if scoped is None:
            return 0
        workspace_id, connection_name = scoped

        provider = str(raw.provider or "channel")[:60]
        provider_label = provider.replace("_", " ").title()
        recipients = await notify_workspace_admins(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            title="Channel webhook processing failed",
            body=(
                f"{connection_name} ({provider_label}) has an inbound webhook event "
                "that failed during processing."
            ),
            dedupe_key=f"{_FAILED_WEBHOOK_INCIDENT_PREFIX}{raw.id}",
            category="channel",
            severity="warning",
            action_url="/integrations",
            action_label="Review webhook activity",
            source_event_id=raw.id,
            metadata={
                "rawEventId": str(raw.id),
                "connectionId": str(connection_id),
                "provider": provider,
                "processingStatus": "failed",
                "errorCode": "processing_failed",
                "incident": "webhook_processing_failed",
            },
        )
        await session.commit()
        return recipients


async def notify_failed_webhook_events(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as session:
        failed = await failed_webhook_events(session)

    for raw_event_id, tenant_id, connection_id in failed:
        try:
            await _notify_failed_webhook_event(
                factory,
                raw_event_id=raw_event_id,
                tenant_id=tenant_id,
                connection_id=connection_id,
            )
        except Exception as exc:
            logger.exception(
                "channel_failed_webhook_notification_failed",
                raw_event_id=str(raw_event_id),
                tenant_id=str(tenant_id),
                connection_id=str(connection_id),
                error=type(exc).__name__,
            )

    try:
        await notify_failed_webhook_recoveries(factory)
    except Exception as exc:
        logger.exception(
            "channel_failed_webhook_recovery_scan_failed",
            error=type(exc).__name__,
        )


async def failed_webhook_recovery_candidates(
    session: AsyncSession,
) -> list[tuple[UUID, UUID, UUID]]:
    """Return completed failed incidents that have not already emitted recovery."""

    recovered_event_ids = select(Notification.source_event_id).where(
        Notification.category == "channel",
        Notification.source_event_id.is_not(None),
        Notification.dedupe_key.like(f"{_FAILED_WEBHOOK_RECOVERY_PREFIX}%"),
    )
    rows = list(
        await session.execute(
            select(
                Notification.tenant_id,
                Notification.workspace_id,
                Notification.source_event_id,
            )
            .join(RawWebhookEvent, RawWebhookEvent.id == Notification.source_event_id)
            .where(
                Notification.category == "channel",
                Notification.workspace_id.is_not(None),
                Notification.source_event_id.is_not(None),
                Notification.dedupe_key.like(f"{_FAILED_WEBHOOK_INCIDENT_PREFIX}%"),
                RawWebhookEvent.tenant_id == Notification.tenant_id,
                RawWebhookEvent.processing_status.in_(_FAILED_WEBHOOK_RECOVERY_STATUSES),
                ~Notification.source_event_id.in_(recovered_event_ids),
            )
            .order_by(Notification.created_at.desc(), Notification.id.desc())
            .limit(FAILED_WEBHOOK_RECOVERY_SCAN_SIZE)
        )
    )

    values: list[tuple[UUID, UUID, UUID]] = []
    seen: set[tuple[UUID, UUID, UUID]] = set()
    for tenant_id, workspace_id, raw_event_id in rows:
        if workspace_id is None or raw_event_id is None:
            continue
        candidate = (tenant_id, workspace_id, raw_event_id)
        if candidate in seen:
            continue
        seen.add(candidate)
        values.append(candidate)
    return values


async def _notify_failed_webhook_recovery(
    factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    raw_event_id: UUID,
) -> int:
    async with factory() as session:
        await set_tenant_context(session, tenant_id)
        raw = await session.scalar(
            select(RawWebhookEvent).where(
                RawWebhookEvent.id == raw_event_id,
                RawWebhookEvent.tenant_id == tenant_id,
                RawWebhookEvent.processing_status.in_(_FAILED_WEBHOOK_RECOVERY_STATUSES),
            )
        )
        if raw is None:
            return 0

        try:
            connection_id = UUID(str(raw.connection_key))
        except (TypeError, ValueError):
            return 0

        provider = str(raw.provider or "channel")[:60]
        final_status = str(raw.processing_status)[:40]
        provider_label = provider.replace("_", " ").title()
        recipients = await notify_workspace_admins(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            title="Channel webhook processing recovered",
            body=(
                f"A previously failed {provider_label} webhook event completed "
                f"with status {final_status}."
            ),
            dedupe_key=f"{_FAILED_WEBHOOK_RECOVERY_PREFIX}{raw.id}",
            category="channel",
            severity="info",
            action_url="/integrations",
            action_label="Review webhook activity",
            source_event_id=raw.id,
            metadata={
                "rawEventId": str(raw.id),
                "connectionId": str(connection_id),
                "provider": provider,
                "finalStatus": final_status,
                "transition": "recovery",
                "incident": "webhook_processing_failed",
            },
        )
        await session.commit()
        return recipients


async def notify_failed_webhook_recoveries(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as session:
        candidates = await failed_webhook_recovery_candidates(session)

    for tenant_id, workspace_id, raw_event_id in candidates:
        try:
            await _notify_failed_webhook_recovery(
                factory,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                raw_event_id=raw_event_id,
            )
        except Exception as exc:
            logger.exception(
                "channel_failed_webhook_recovery_notification_failed",
                tenant_id=str(tenant_id),
                workspace_id=str(workspace_id),
                raw_event_id=str(raw_event_id),
                error=type(exc).__name__,
            )
