from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from northstar_api.database import Base
from northstar_api.lead_crm.channel_models import ChannelConnection
from northstar_api.lead_crm.channel_scope import WorkspaceChannelConnection
from northstar_api.lead_crm.models import RawWebhookEvent
from northstar_api.models import (
    Agent,
    OutboxEvent,
    Role,
    Tenant,
    User,
    Workspace,
    WorkspaceMembership,
    WorkspaceRole,
)
from northstar_api.notifications import Notification
from northstar_api.routers.channel_operations import channel_operational_health
from northstar_api.routers.channel_webhook_events import requeue_failed_channel_webhook
from northstar_api.security import Principal
from northstar_api.workers import channel_health_monitor


@pytest.fixture
async def requeue_stale_timing_case() -> AsyncIterator[
    tuple[async_sessionmaker[AsyncSession], Principal, dict[str, UUID], datetime]
]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        tenant = Tenant(slug=f"requeue-stale-{uuid4().hex}", name="Requeue stale timing")
        admin = User(
            email=f"requeue-stale-{uuid4().hex}@example.test",
            name="Channel Admin",
            password_hash="test-only",
            is_active=True,
        )
        session.add_all([tenant, admin])
        await session.flush()

        workspace = Workspace(
            tenant_id=tenant.id,
            name="Messaging workspace",
            slug=f"messaging-{uuid4().hex[:8]}",
            created_by=admin.id,
        )
        session.add(workspace)
        await session.flush()
        session.add(
            WorkspaceMembership(
                tenant_id=tenant.id,
                workspace_id=workspace.id,
                user_id=admin.id,
                role=WorkspaceRole.ADMIN,
            )
        )

        agent = Agent(tenant_id=tenant.id, workspace_id=workspace.id, name="Messaging agent")
        session.add(agent)
        await session.flush()

        channel = ChannelConnection(
            tenant_id=tenant.id,
            provider="telegram",
            name="Primary Telegram",
            status="healthy",
            configuration_json={"agentId": str(agent.id)},
        )
        session.add(channel)
        await session.flush()
        session.add(
            WorkspaceChannelConnection(
                tenant_id=tenant.id,
                workspace_id=workspace.id,
                agent_id=agent.id,
                connection_id=channel.id,
            )
        )

        original_received_at = datetime.now(UTC) - timedelta(minutes=30)
        replayable = RawWebhookEvent(
            tenant_id=tenant.id,
            connection_key=str(channel.id),
            provider="telegram",
            external_event_id=f"replayable-{uuid4().hex}",
            event_type="message.received",
            payload_json={"text": "private replayable message", "token": "must-not-leak"},
            headers_json={"authorization": "Bearer must-not-leak"},
            payload_hash="a" * 64,
            verification_status="verified",
            processing_status="failed",
            attempt_count=2,
            received_at=original_received_at,
            last_error="agent_not_configured",
            correlation_id="private-replay-correlation",
        )
        session.add(replayable)
        await session.commit()

        principal = Principal(
            user_id=admin.id,
            tenant_id=tenant.id,
            role=Role.ADMIN,
            token_id="requeue-stale-timing",
            workspace_id=workspace.id,
            workspace_role=WorkspaceRole.ADMIN,
            permissions=frozenset({"integrations.view", "integrations.manage"}),
        )
        yield factory, principal, {
            "raw_event": replayable.id,
            "connection": channel.id,
        }, original_received_at

    await engine.dispose()


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def test_manual_requeue_resets_stale_age_without_rewriting_raw_receipt(
    requeue_stale_timing_case,
) -> None:
    factory, principal, ids, original_received_at = requeue_stale_timing_case

    async with factory() as session:
        result = await requeue_failed_channel_webhook(ids["raw_event"], principal, session)
        assert result.processing_status == "received"

    now = datetime.now(UTC)
    async with factory() as session:
        raw = await session.get(RawWebhookEvent, ids["raw_event"])
        assert raw is not None
        assert _aware(raw.received_at) == _aware(original_received_at)
        assert raw.attempt_count == 2
        assert raw.last_error is None

        outbox = await session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.tenant_id == principal.tenant_id,
                OutboxEvent.aggregate_type == "raw_webhook_event",
                OutboxEvent.aggregate_id == str(ids["raw_event"]),
                OutboxEvent.event_type == "channel.event.received.v1",
            )
        )
        assert outbox is not None
        assert _aware(outbox.occurred_at) > _aware(original_received_at)

        stale = await channel_health_monitor._stale_webhook_events(session, now=now)
        assert ids["raw_event"] not in {raw_event_id for raw_event_id, *_ in stale}

        health = await channel_operational_health(principal, session)
        assert health.pending_webhook_events == 1
        assert health.stale_webhook_events == 0
        assert health.attention_connections == 0
        assert health.overall_status == "active"

    recipients = await channel_health_monitor._notify_stale_webhook_event(
        factory,
        raw_event_id=ids["raw_event"],
        tenant_id=principal.tenant_id,
        connection_id=ids["connection"],
        now=now,
    )
    assert recipients == 0

    async with factory() as session:
        stale_notification = await session.scalar(
            select(Notification.id).where(
                Notification.dedupe_key == f"channel-webhook-stale:{ids['raw_event']}"
            )
        )
        assert stale_notification is None


async def test_requeued_event_becomes_stale_after_latest_enqueue_ages(
    requeue_stale_timing_case,
) -> None:
    factory, principal, ids, _original_received_at = requeue_stale_timing_case

    async with factory() as session:
        await requeue_failed_channel_webhook(ids["raw_event"], principal, session)

    now = datetime.now(UTC)
    async with factory() as session:
        outbox = await session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.tenant_id == principal.tenant_id,
                OutboxEvent.aggregate_type == "raw_webhook_event",
                OutboxEvent.aggregate_id == str(ids["raw_event"]),
                OutboxEvent.event_type == "channel.event.received.v1",
            )
        )
        assert outbox is not None
        outbox.occurred_at = now - timedelta(minutes=10)
        await session.commit()

    async with factory() as session:
        stale = await channel_health_monitor._stale_webhook_events(session, now=now)
        assert ids["raw_event"] in {raw_event_id for raw_event_id, *_ in stale}

        health = await channel_operational_health(principal, session)
        assert health.stale_webhook_events == 1
        assert health.attention_connections == 1
        assert health.overall_status == "attention"

    recipients = await channel_health_monitor._notify_stale_webhook_event(
        factory,
        raw_event_id=ids["raw_event"],
        tenant_id=principal.tenant_id,
        connection_id=ids["connection"],
        now=now,
    )
    assert recipients == 1

    async with factory() as session:
        notification = await session.scalar(
            select(Notification).where(
                Notification.dedupe_key == f"channel-webhook-stale:{ids['raw_event']}"
            )
        )
        assert notification is not None
        assert notification.source_event_id == ids["raw_event"]


async def test_legacy_received_event_without_outbox_falls_back_to_raw_received_at(
    requeue_stale_timing_case,
) -> None:
    factory, principal, ids, original_received_at = requeue_stale_timing_case

    async with factory() as session:
        raw = await session.get(RawWebhookEvent, ids["raw_event"])
        assert raw is not None
        raw.processing_status = "received"
        raw.last_error = None
        await session.execute(
            delete(OutboxEvent).where(
                OutboxEvent.tenant_id == principal.tenant_id,
                OutboxEvent.aggregate_type == "raw_webhook_event",
                OutboxEvent.aggregate_id == str(ids["raw_event"]),
            )
        )
        await session.commit()

    now = _aware(original_received_at) + timedelta(minutes=10)
    async with factory() as session:
        stale = await channel_health_monitor._stale_webhook_events(session, now=now)
        assert ids["raw_event"] in {raw_event_id for raw_event_id, *_ in stale}
