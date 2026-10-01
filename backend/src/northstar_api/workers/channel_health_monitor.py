from __future__ import annotations

import asyncio
import signal
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from northstar_api.config import get_settings
from northstar_api.database import build_engine, set_tenant_context
from northstar_api.lead_crm.channel_models import ChannelConnection, ChannelHealthSnapshot
from northstar_api.lead_crm.channel_scope import WorkspaceChannelConnection
from northstar_api.lead_crm.channel_webhook_timing import channel_webhook_pending_since_expression
from northstar_api.lead_crm.channels import ChannelConnectionContext, channel_registry
from northstar_api.lead_crm.credentials import CredentialStoreError, credential_store
from northstar_api.lead_crm.domain import ChannelProvider
from northstar_api.lead_crm.models import RawWebhookEvent
from northstar_api.logging import configure_logging
from northstar_api.notifications import Notification
from northstar_api.services.notifications import notify_workspace_admins
from northstar_api.workers.channel_webhook_failure_notifications import notify_failed_webhook_events

settings = get_settings()
configure_logging(settings)
logger = structlog.get_logger(__name__)

HEALTH_INTERVAL_SECONDS = 300
RECOVERY_POLL_INTERVAL_SECONDS = 10
RECOVERY_FAST_INTERVAL_SECONDS = 15
RECOVERY_MEDIUM_INTERVAL_SECONDS = 30
RECOVERY_SLOW_INTERVAL_SECONDS = 60
RECOVERY_MEDIUM_AFTER_SECONDS = 60
RECOVERY_SLOW_AFTER_SECONDS = 300
HEALTH_BATCH_SIZE = 50
STALE_WEBHOOK_BATCH_SIZE = 100
STALE_WEBHOOK_SCAN_PAGE_SIZE = 250
STALE_WEBHOOK_RECOVERY_SCAN_SIZE = 500
STALE_WEBHOOK_RECOVERY_PAGE_SIZE = 250
_STALE_WEBHOOK_AFTER = timedelta(minutes=5)
_STALE_WEBHOOK_INCIDENT_PREFIX = "channel-webhook-stale:"
_STALE_WEBHOOK_RECOVERY_PREFIX = "channel-webhook-stale-recovery:"
_STALE_WEBHOOK_RECOVERY_STATUSES = frozenset({"processed", "ignored", "rejected"})
_ELIGIBLE_STATUSES = frozenset(
    {
        "configured",
        "healthy",
        "degraded",
        "unhealthy",
        "auth_required",
        "rate_limited",
        "configuration_error",
        "unknown",
    }
)
_FAILURE_STATUSES = frozenset(
    {
        "degraded",
        "unhealthy",
        "auth_required",
        "rate_limited",
        "configuration_error",
    }
)
_ATTENTION_STATUSES = _FAILURE_STATUSES
_TRANSIENT_RECOVERY_STATUSES = frozenset({"degraded", "unhealthy"})
_KNOWN_HEALTH_STATUSES = _ELIGIBLE_STATUSES - {"configured"}


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _is_due(connection: ChannelConnection, *, now: datetime) -> bool:
    if connection.status not in _ELIGIBLE_STATUSES:
        return False
    if connection.last_health_at is None:
        return True
    interval = HEALTH_INTERVAL_SECONDS
    if connection.status in _TRANSIENT_RECOVERY_STATUSES:
        failure_at = connection.last_failure_at
        failure_age = (now - _aware(failure_at)).total_seconds() if failure_at else 0
        if failure_age < RECOVERY_MEDIUM_AFTER_SECONDS:
            interval = RECOVERY_FAST_INTERVAL_SECONDS
        elif failure_age < RECOVERY_SLOW_AFTER_SECONDS:
            interval = RECOVERY_MEDIUM_INTERVAL_SECONDS
        else:
            interval = RECOVERY_SLOW_INTERVAL_SECONDS
    cutoff = now - timedelta(seconds=interval)
    return _aware(connection.last_health_at) <= cutoff


def _normalized_health_status(value: object) -> str:
    normalized = str(value or "unknown").strip().lower()[:40]
    return normalized if normalized in _KNOWN_HEALTH_STATUSES else "unknown"


def _context(connection: ChannelConnection, credentials: dict[str, Any]) -> ChannelConnectionContext:
    return ChannelConnectionContext(
        tenant_id=connection.tenant_id,
        connection_id=connection.id,
        provider=ChannelProvider(connection.provider),
        configuration=dict(connection.configuration_json or {}),
        credentials=dict(credentials),
        public_id=connection.public_id,
    )


def _record_status(
    connection: ChannelConnection,
    *,
    status: str,
    checked_at: datetime,
    error_code: str | None = None,
) -> None:
    previous_status = connection.status
    connection.status = status
    connection.last_health_at = checked_at
    if status == "healthy":
        connection.last_error = None
        return
    if status in _FAILURE_STATUSES and (
        previous_status not in _FAILURE_STATUSES or connection.last_failure_at is None
    ):
        connection.last_failure_at = checked_at
    if error_code:
        connection.last_error = f"Scheduled channel health check failed: {error_code}"[:1000]
    else:
        connection.last_error = f"Scheduled channel health check reported {status}"[:1000]


def _health_transition(previous_status: str, current_status: str) -> str | None:
    """Return an actionable transition while suppressing repeated poll alerts."""

    previous_attention = previous_status in _ATTENTION_STATUSES
    current_attention = current_status in _ATTENTION_STATUSES
    if current_attention and not previous_attention:
        return "incident"
    if previous_attention and current_status == "healthy":
        return "recovery"
    return None


async def _notify_health_transition(
    factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    connection_id: UUID,
    connection_name: str,
    provider: str,
    previous_status: str,
    current_status: str,
    checked_at: datetime,
) -> int:
    transition = _health_transition(previous_status, current_status)
    if transition is None:
        return 0

    async with factory() as session:
        await set_tenant_context(session, tenant_id)
        workspace_id = await session.scalar(
            select(WorkspaceChannelConnection.workspace_id).where(
                WorkspaceChannelConnection.tenant_id == tenant_id,
                WorkspaceChannelConnection.connection_id == connection_id,
            )
        )
        if workspace_id is None:
            return 0

        provider_label = provider.replace("_", " ").title()
        metadata = {
            "connectionId": str(connection_id),
            "provider": provider,
            "previousStatus": previous_status,
            "currentStatus": current_status,
            "transition": transition,
        }
        if transition == "incident":
            title = "Channel connection needs attention"
            body = (
                f"{connection_name} ({provider_label}) changed from "
                f"{previous_status} to {current_status}."
            )
            severity = "warning"
        else:
            title = "Channel connection recovered"
            body = f"{connection_name} ({provider_label}) is healthy again."
            severity = "info"

        recipients = await notify_workspace_admins(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            title=title,
            body=body,
            dedupe_key=(
                f"channel-health:{connection_id}:{transition}:"
                f"{_aware(checked_at).isoformat()}"
            ),
            category="channel",
            severity=severity,
            action_url="/integrations",
            action_label="Review channel health",
            metadata=metadata,
        )
        await session.commit()
        return recipients


async def _stale_webhook_events(
    session: AsyncSession,
    *,
    now: datetime,
) -> list[tuple[UUID, UUID, UUID]]:
    """Return unalerted bound stale events using the latest queue/requeue timestamp."""

    cutoff = now - _STALE_WEBHOOK_AFTER
    bound_connection_ids = list(
        await session.scalars(select(WorkspaceChannelConnection.connection_id).distinct())
    )
    if not bound_connection_ids:
        return []

    alerted_event_ids = select(Notification.source_event_id).where(
        Notification.category == "channel",
        Notification.source_event_id.is_not(None),
        Notification.dedupe_key.like(f"{_STALE_WEBHOOK_INCIDENT_PREFIX}%"),
    )
    pending_since = channel_webhook_pending_since_expression()
    values: list[tuple[UUID, UUID, UUID]] = []
    cursor_pending_since: datetime | None = None
    cursor_id: UUID | None = None

    while len(values) < STALE_WEBHOOK_BATCH_SIZE:
        query = select(
            RawWebhookEvent.id,
            RawWebhookEvent.tenant_id,
            RawWebhookEvent.connection_key,
            pending_since.label("pending_since"),
        ).where(
            RawWebhookEvent.processing_status == "received",
            pending_since <= cutoff,
            RawWebhookEvent.connection_key.in_([str(value) for value in bound_connection_ids]),
            ~RawWebhookEvent.id.in_(alerted_event_ids),
        )
        if cursor_pending_since is not None and cursor_id is not None:
            query = query.where(
                or_(
                    pending_since > cursor_pending_since,
                    and_(
                        pending_since == cursor_pending_since,
                        RawWebhookEvent.id > cursor_id,
                    ),
                )
            )
        rows = list(
            await session.execute(
                query.order_by(pending_since, RawWebhookEvent.id).limit(
                    STALE_WEBHOOK_SCAN_PAGE_SIZE
                )
            )
        )
        if not rows:
            break

        incident_keys = [f"{_STALE_WEBHOOK_INCIDENT_PREFIX}{raw_event_id}" for raw_event_id, *_ in rows]
        existing_keys = set(
            await session.scalars(
                select(Notification.dedupe_key).where(
                    Notification.category == "channel",
                    Notification.dedupe_key.in_(incident_keys),
                )
            )
        )
        for raw_event_id, tenant_id, connection_key, _pending_since in rows:
            if f"{_STALE_WEBHOOK_INCIDENT_PREFIX}{raw_event_id}" in existing_keys:
                continue
            try:
                connection_id = UUID(str(connection_key))
            except (TypeError, ValueError):
                continue
            values.append((raw_event_id, tenant_id, connection_id))
            if len(values) >= STALE_WEBHOOK_BATCH_SIZE:
                break

        cursor_pending_since = rows[-1][3]
        cursor_id = rows[-1][0]
        if len(rows) < STALE_WEBHOOK_SCAN_PAGE_SIZE:
            break

    return values


async def _notify_stale_webhook_event(
    factory: async_sessionmaker[AsyncSession],
    *,
    raw_event_id: UUID,
    tenant_id: UUID,
    connection_id: UUID,
    now: datetime,
) -> int:
    """Project one still-stale channel webhook into a deduplicated admin notification."""

    cutoff = now - _STALE_WEBHOOK_AFTER
    async with factory() as session:
        await set_tenant_context(session, tenant_id)
        pending_since = channel_webhook_pending_since_expression()
        raw = await session.scalar(
            select(RawWebhookEvent).where(
                RawWebhookEvent.id == raw_event_id,
                RawWebhookEvent.tenant_id == tenant_id,
                RawWebhookEvent.connection_key == str(connection_id),
                RawWebhookEvent.processing_status == "received",
                pending_since <= cutoff,
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
        metadata = {
            "rawEventId": str(raw.id),
            "connectionId": str(connection_id),
            "provider": provider,
            "processingStatus": "received",
            "incident": "stale_webhook",
        }
        recipients = await notify_workspace_admins(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            title="Channel webhook processing is delayed",
            body=(
                f"{connection_name} ({provider_label}) has an inbound webhook event "
                "that has remained pending for more than 5 minutes."
            ),
            dedupe_key=f"{_STALE_WEBHOOK_INCIDENT_PREFIX}{raw.id}",
            category="channel",
            severity="warning",
            action_url="/integrations",
            action_label="Review webhook activity",
            source_event_id=raw.id,
            metadata=metadata,
        )
        await session.commit()
        return recipients


async def _notify_stale_webhook_events(
    factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime,
) -> None:
    async with factory() as session:
        stale = await _stale_webhook_events(session, now=now)

    for raw_event_id, tenant_id, connection_id in stale:
        try:
            await _notify_stale_webhook_event(
                factory,
                raw_event_id=raw_event_id,
                tenant_id=tenant_id,
                connection_id=connection_id,
                now=now,
            )
        except Exception as exc:
            logger.exception(
                "channel_stale_webhook_notification_failed",
                raw_event_id=str(raw_event_id),
                tenant_id=str(tenant_id),
                connection_id=str(connection_id),
                error=type(exc).__name__,
            )


async def _stale_webhook_recovery_candidates(
    session: AsyncSession,
) -> list[tuple[UUID, UUID, UUID]]:
    """Return unrecovered completed stale incidents without bounded-scan starvation."""

    values: list[tuple[UUID, UUID, UUID]] = []
    seen: set[tuple[UUID, UUID, UUID]] = set()
    cursor_created_at: datetime | None = None
    cursor_id: UUID | None = None

    while len(values) < STALE_WEBHOOK_RECOVERY_SCAN_SIZE:
        query = select(
            Notification.tenant_id,
            Notification.workspace_id,
            Notification.dedupe_key,
            Notification.source_event_id,
            Notification.created_at,
            Notification.id,
        ).where(
            Notification.category == "channel",
            Notification.workspace_id.is_not(None),
            Notification.dedupe_key.like(f"{_STALE_WEBHOOK_INCIDENT_PREFIX}%"),
            ~Notification.dedupe_key.like(f"{_STALE_WEBHOOK_RECOVERY_PREFIX}%"),
        )
        if cursor_created_at is not None and cursor_id is not None:
            query = query.where(
                or_(
                    Notification.created_at < cursor_created_at,
                    and_(
                        Notification.created_at == cursor_created_at,
                        Notification.id < cursor_id,
                    ),
                )
            )
        rows = list(
            await session.execute(
                query.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(
                    STALE_WEBHOOK_RECOVERY_PAGE_SIZE
                )
            )
        )
        if not rows:
            break

        parsed_rows: list[tuple[UUID, UUID, UUID]] = []
        for tenant_id, workspace_id, dedupe_key, source_event_id, _created_at, _notification_id in rows:
            if workspace_id is None:
                continue
            try:
                raw_event_id = UUID(dedupe_key.removeprefix(_STALE_WEBHOOK_INCIDENT_PREFIX))
            except ValueError:
                continue
            if source_event_id is not None and source_event_id != raw_event_id:
                continue
            parsed_rows.append((tenant_id, workspace_id, raw_event_id))

        raw_ids = list({raw_event_id for _, _, raw_event_id in parsed_rows})
        recovery_keys = [f"{_STALE_WEBHOOK_RECOVERY_PREFIX}{raw_event_id}" for raw_event_id in raw_ids]
        recovered_keys = (
            set(
                await session.scalars(
                    select(Notification.dedupe_key).where(
                        Notification.category == "channel",
                        Notification.dedupe_key.in_(recovery_keys),
                    )
                )
            )
            if recovery_keys
            else set()
        )
        raw_states = {
            raw_event_id: (tenant_id, processing_status)
            for raw_event_id, tenant_id, processing_status in await session.execute(
                select(
                    RawWebhookEvent.id,
                    RawWebhookEvent.tenant_id,
                    RawWebhookEvent.processing_status,
                ).where(RawWebhookEvent.id.in_(raw_ids))
            )
        } if raw_ids else {}

        for tenant_id, workspace_id, raw_event_id in parsed_rows:
            candidate = (tenant_id, workspace_id, raw_event_id)
            if candidate in seen:
                continue
            if f"{_STALE_WEBHOOK_RECOVERY_PREFIX}{raw_event_id}" in recovered_keys:
                seen.add(candidate)
                continue
            raw_state = raw_states.get(raw_event_id)
            if raw_state is None or raw_state[0] != tenant_id:
                continue
            if raw_state[1] not in _STALE_WEBHOOK_RECOVERY_STATUSES:
                continue
            seen.add(candidate)
            values.append(candidate)
            if len(values) >= STALE_WEBHOOK_RECOVERY_SCAN_SIZE:
                break

        cursor_created_at = rows[-1][4]
        cursor_id = rows[-1][5]
        if len(rows) < STALE_WEBHOOK_RECOVERY_PAGE_SIZE:
            break

    return values


async def _notify_stale_webhook_recovery(
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
                RawWebhookEvent.processing_status.in_(_STALE_WEBHOOK_RECOVERY_STATUSES),
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
                f"A previously delayed {provider_label} webhook event completed "
                f"with status {final_status}."
            ),
            dedupe_key=f"{_STALE_WEBHOOK_RECOVERY_PREFIX}{raw.id}",
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
            },
        )
        await session.commit()
        return recipients


async def _notify_stale_webhook_recoveries(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as session:
        candidates = await _stale_webhook_recovery_candidates(session)

    for tenant_id, workspace_id, raw_event_id in candidates:
        try:
            await _notify_stale_webhook_recovery(
                factory,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                raw_event_id=raw_event_id,
            )
        except Exception as exc:
            logger.exception(
                "channel_stale_webhook_recovery_notification_failed",
                tenant_id=str(tenant_id),
                workspace_id=str(workspace_id),
                raw_event_id=str(raw_event_id),
                error=type(exc).__name__,
            )


async def _due_connections(session: AsyncSession, *, now: datetime) -> list[tuple[UUID, UUID]]:
    cutoff = now - timedelta(seconds=HEALTH_INTERVAL_SECONDS)
    fast_cutoff = now - timedelta(seconds=RECOVERY_FAST_INTERVAL_SECONDS)
    medium_cutoff = now - timedelta(seconds=RECOVERY_MEDIUM_INTERVAL_SECONDS)
    slow_cutoff = now - timedelta(seconds=RECOVERY_SLOW_INTERVAL_SECONDS)
    medium_failure_cutoff = now - timedelta(seconds=RECOVERY_MEDIUM_AFTER_SECONDS)
    slow_failure_cutoff = now - timedelta(seconds=RECOVERY_SLOW_AFTER_SECONDS)
    recovery_due = or_(
        and_(
            ChannelConnection.last_failure_at.is_(None),
            ChannelConnection.last_health_at <= fast_cutoff,
        ),
        and_(
            ChannelConnection.last_failure_at > medium_failure_cutoff,
            ChannelConnection.last_health_at <= fast_cutoff,
        ),
        and_(
            ChannelConnection.last_failure_at <= medium_failure_cutoff,
            ChannelConnection.last_failure_at > slow_failure_cutoff,
            ChannelConnection.last_health_at <= medium_cutoff,
        ),
        and_(
            ChannelConnection.last_failure_at <= slow_failure_cutoff,
            ChannelConnection.last_health_at <= slow_cutoff,
        ),
    )
    rows = list(
        await session.execute(
            select(ChannelConnection.id, ChannelConnection.tenant_id)
            .where(
                ChannelConnection.status.in_(_ELIGIBLE_STATUSES),
                or_(
                    ChannelConnection.last_health_at.is_(None),
                    and_(
                        ChannelConnection.status.in_(_TRANSIENT_RECOVERY_STATUSES),
                        recovery_due,
                    ),
                    and_(
                        ChannelConnection.status.not_in(_TRANSIENT_RECOVERY_STATUSES),
                        ChannelConnection.last_health_at <= cutoff,
                    ),
                ),
            )
            .order_by(ChannelConnection.last_health_at.asc().nullsfirst(), ChannelConnection.id)
            .limit(HEALTH_BATCH_SIZE)
        )
    )
    return [(connection_id, tenant_id) for connection_id, tenant_id in rows]


async def monitor_connection(
    factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    connection_id: UUID,
    now: datetime | None = None,
) -> bool:
    """Check one due channel connection using its existing connector contract."""

    checked_at = now or datetime.now(UTC)
    previous_status: str
    current_status: str
    current_error_code: str | None
    connection_name: str
    provider: str

    async with factory() as session:
        await set_tenant_context(session, tenant_id)
        connection = await session.scalar(
            select(ChannelConnection)
            .where(
                ChannelConnection.id == connection_id,
                ChannelConnection.tenant_id == tenant_id,
            )
            .with_for_update()
        )
        if connection is None or not _is_due(connection, now=checked_at):
            await session.commit()
            return False

        previous_status = connection.status
        current_status = previous_status
        current_error_code = None
        connection_name = connection.name
        provider = connection.provider
        credentials: dict[str, Any] = {}
        credentials_ready = True
        if connection.credentials_encrypted:
            try:
                credentials = credential_store.decrypt(connection.credentials_encrypted)
            except CredentialStoreError:
                credentials_ready = False
                current_status = "auth_required"
                current_error_code = "credential_error"
                _record_status(
                    connection,
                    status=current_status,
                    checked_at=checked_at,
                    error_code=current_error_code,
                )

        if credentials_ready:
            try:
                context = _context(connection, credentials)
                connector = channel_registry.get(context.provider)
            except (KeyError, ValueError):
                current_status = "configuration_error"
                current_error_code = "configuration_error"
                _record_status(
                    connection,
                    status=current_status,
                    checked_at=checked_at,
                    error_code=current_error_code,
                )
            else:
                result = await connector.health_check(context)
                current_status = _normalized_health_status(result.get("status"))
                _record_status(connection, status=current_status, checked_at=checked_at)

        session.add(
            ChannelHealthSnapshot(
                tenant_id=tenant_id,
                connection_id=connection_id,
                status=current_status,
                error_code=current_error_code,
                checked_at=checked_at,
            )
        )
        await session.commit()

    if _health_transition(previous_status, current_status) is not None:
        try:
            await _notify_health_transition(
                factory,
                tenant_id=tenant_id,
                connection_id=connection_id,
                connection_name=connection_name,
                provider=provider,
                previous_status=previous_status,
                current_status=current_status,
                checked_at=checked_at,
            )
        except Exception as exc:
            # Health persistence is primary. A notification failure cannot undo
            # the completed provider check or its durable connection status.
            logger.exception(
                "channel_health_monitor_notification_failed",
                tenant_id=str(tenant_id),
                connection_id=str(connection_id),
                previous_status=previous_status,
                current_status=current_status,
                error=type(exc).__name__,
            )

    return True


async def run_once(factory: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    now = datetime.now(UTC)
    async with factory() as session:
        due = await _due_connections(session, now=now)

    checked = 0
    failed = 0
    for connection_id, tenant_id in due:
        try:
            if await monitor_connection(
                factory,
                tenant_id=tenant_id,
                connection_id=connection_id,
                now=now,
            ):
                checked += 1
        except Exception as exc:
            failed += 1
            logger.exception(
                "channel_health_monitor_connection_failed",
                connection_id=str(connection_id),
                tenant_id=str(tenant_id),
                error=type(exc).__name__,
            )

    try:
        await _notify_stale_webhook_events(factory, now=now)
    except Exception as exc:
        # Stale-event notifications are a secondary operational projection.
        # Their failure must not alter the existing health-monitor contract.
        logger.exception(
            "channel_stale_webhook_scan_failed",
            error=type(exc).__name__,
        )

    try:
        await _notify_stale_webhook_recoveries(factory)
    except Exception as exc:
        logger.exception(
            "channel_stale_webhook_recovery_scan_failed",
            error=type(exc).__name__,
        )

    try:
        await notify_failed_webhook_events(factory)
    except Exception as exc:
        logger.exception(
            "channel_failed_webhook_scan_failed",
            error=type(exc).__name__,
        )

    return {"due": len(due), "checked": checked, "failed": failed}


async def run_forever() -> None:
    engine = build_engine(settings)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signal_name, stop.set)
        except NotImplementedError:
            pass

    logger.info(
        "channel_health_monitor_started",
        interval_seconds=HEALTH_INTERVAL_SECONDS,
        recovery_poll_interval_seconds=RECOVERY_POLL_INTERVAL_SECONDS,
        batch_size=HEALTH_BATCH_SIZE,
    )
    try:
        while not stop.is_set():
            result = await run_once(factory)
            if result["due"] or result["failed"]:
                logger.info("channel_health_monitor_completed", **result)
            try:
                await asyncio.wait_for(stop.wait(), timeout=float(RECOVERY_POLL_INTERVAL_SECONDS))
            except TimeoutError:
                pass
    finally:
        await engine.dispose()
        logger.info("channel_health_monitor_stopped")


def main() -> None:
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
