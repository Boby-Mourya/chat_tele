from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from northstar_api.database import Base
from northstar_api.lead_crm.channel_models import ChannelConnection
from northstar_api.lead_crm.channel_scope import WorkspaceChannelConnection
from northstar_api.lead_crm.models import RawWebhookEvent
from northstar_api.models import Tenant, User, Workspace, WorkspaceMembership, WorkspaceRole
from northstar_api.notifications import Notification
from northstar_api.workers import channel_health_monitor


@pytest.fixture
async def stale_webhook_notification_case() -> AsyncIterator[
    tuple[
        async_sessionmaker[AsyncSession],
        UUID,
        UUID,
        UUID,
        UUID,
        UUID,
        UUID,
    ]
]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        tenant = Tenant(slug=f"stale-webhook-{uuid4().hex}", name="Stale webhook tenant")
        primary_admin = User(
            email=f"primary-admin-{uuid4().hex}@example.test",
            name="Primary Admin",
            password_hash="not-used-by-this-test",
            is_active=True,
        )
        other_admin = User(
            email=f"other-admin-{uuid4().hex}@example.test",
            name="Other Admin",
            password_hash="not-used-by-this-test",
            is_active=True,
        )
        session.add_all([tenant, primary_admin, other_admin])
        await session.flush()

        primary_workspace = Workspace(
            tenant_id=tenant.id,
            name="Primary messaging",
            slug=f"primary-messaging-{uuid4().hex[:8]}",
            created_by=primary_admin.id,
        )
        other_workspace = Workspace(
            tenant_id=tenant.id,
            name="Other messaging",
            slug=f"other-messaging-{uuid4().hex[:8]}",
            created_by=other_admin.id,
        )
        session.add_all([primary_workspace, other_workspace])
        await session.flush()
        session.add_all(
            [
                WorkspaceMembership(
                    tenant_id=tenant.id,
                    workspace_id=primary_workspace.id,
                    user_id=primary_admin.id,
                    role=WorkspaceRole.ADMIN,
                ),
                WorkspaceMembership(
                    tenant_id=tenant.id,
                    workspace_id=other_workspace.id,
                    user_id=other_admin.id,
                    role=WorkspaceRole.ADMIN,
                ),
            ]
        )

        primary_connection = ChannelConnection(
            tenant_id=tenant.id,
            provider="telegram",
            name="Primary Telegram",
            status="healthy",
            configuration_json={},
        )
        other_connection = ChannelConnection(
            tenant_id=tenant.id,
            provider="slack",
            name="Other Slack",
            status="healthy",
            configuration_json={},
        )
        unbound_connection = ChannelConnection(
            tenant_id=tenant.id,
            provider="instagram",
            name="Unbound Instagram",
            status="healthy",
            configuration_json={},
        )
        session.add_all([primary_connection, other_connection, unbound_connection])
        await session.flush()
        session.add_all(
            [
                WorkspaceChannelConnection(
                    tenant_id=tenant.id,
                    workspace_id=primary_workspace.id,
                    agent_id=None,
                    connection_id=primary_connection.id,
                ),
                WorkspaceChannelConnection(
                    tenant_id=tenant.id,
                    workspace_id=other_workspace.id,
                    agent_id=None,
                    connection_id=other_connection.id,
                ),
            ]
        )
        await session.flush()

        now = datetime(2026, 9, 12, 20, 0, tzinfo=UTC)
        primary_stale = RawWebhookEvent(
            tenant_id=tenant.id,
            connection_key=str(primary_connection.id),
            provider="telegram",
            external_event_id="primary-stale-private-external-id",
            event_type="message.received",
            payload_json={"text": "private student message", "token": "must-not-leak"},
            headers_json={"authorization": "Bearer must-not-leak"},
            payload_hash="a" * 64,
            verification_status="verified",
            processing_status="received",
            attempt_count=0,
            received_at=now - timedelta(minutes=10),
            last_error="private stale error must not leak",
            correlation_id="private-correlation-primary",
        )
        other_stale = RawWebhookEvent(
            tenant_id=tenant.id,
            connection_key=str(other_connection.id),
            provider="slack",
            external_event_id="other-stale-private-external-id",
            event_type="message.received",
            payload_json={"text": "other private message"},
            headers_json={"x-slack-signature": "private-signature"},
            payload_hash="b" * 64,
            verification_status="verified",
            processing_status="received",
            attempt_count=0,
            received_at=now - timedelta(minutes=11),
            correlation_id="private-correlation-other",
        )
        fresh = RawWebhookEvent(
            tenant_id=tenant.id,
            connection_key=str(primary_connection.id),
            provider="telegram",
            external_event_id="fresh-event",
            event_type="message.received",
            payload_json={"text": "fresh private message"},
            headers_json={},
            payload_hash="c" * 64,
            verification_status="verified",
            processing_status="received",
            attempt_count=0,
            received_at=now - timedelta(minutes=1),
            correlation_id="fresh-correlation",
        )
        processed = RawWebhookEvent(
            tenant_id=tenant.id,
            connection_key=str(primary_connection.id),
            provider="telegram",
            external_event_id="processed-event",
            event_type="message.received",
            payload_json={"text": "processed private message"},
            headers_json={},
            payload_hash="d" * 64,
            verification_status="verified",
            processing_status="processed",
            attempt_count=1,
            received_at=now - timedelta(minutes=20),
            processed_at=now - timedelta(minutes=19),
            correlation_id="processed-correlation",
        )
        unbound_stale = RawWebhookEvent(
            tenant_id=tenant.id,
            connection_key=str(unbound_connection.id),
            provider="instagram",
            external_event_id="unbound-stale-event",
            event_type="message.received",
            payload_json={"text": "unbound private message"},
            headers_json={},
            payload_hash="e" * 64,
            verification_status="verified",
            processing_status="received",
            attempt_count=0,
            received_at=now - timedelta(minutes=15),
            correlation_id="unbound-correlation",
        )
        session.add_all([primary_stale, other_stale, fresh, processed, unbound_stale])
        await session.commit()
        await session.refresh(primary_stale)
        await session.refresh(other_stale)

        yield (
            factory,
            tenant.id,
            primary_workspace.id,
            other_workspace.id,
            primary_admin.id,
            other_admin.id,
            primary_stale.id,
        )

    await engine.dispose()


async def test_stale_webhooks_notify_only_their_workspace_admin_once_and_remain_secret_safe(
    stale_webhook_notification_case,
) -> None:
    (
        factory,
        _tenant_id,
        primary_workspace_id,
        other_workspace_id,
        primary_admin_id,
        other_admin_id,
        primary_stale_id,
    ) = stale_webhook_notification_case
    now = datetime(2026, 9, 12, 20, 0, tzinfo=UTC)

    await channel_health_monitor._notify_stale_webhook_events(factory, now=now)
    await channel_health_monitor._notify_stale_webhook_events(factory, now=now)

    async with factory() as session:
        notifications = list(
            await session.scalars(select(Notification).order_by(Notification.recipient_user_id))
        )
        assert len(notifications) == 2
        by_recipient = {value.recipient_user_id: value for value in notifications}

        primary = by_recipient[primary_admin_id]
        assert primary.workspace_id == primary_workspace_id
        assert primary.category == "channel"
        assert primary.severity == "warning"
        assert primary.title == "Channel webhook processing is delayed"
        assert primary.action_url == "/integrations"
        assert primary.action_label == "Review webhook activity"
        assert primary.dedupe_key == f"channel-webhook-stale:{primary_stale_id}"
        assert primary.metadata_json == {
            "rawEventId": str(primary_stale_id),
            "connectionId": primary.metadata_json["connectionId"],
            "provider": "telegram",
            "processingStatus": "received",
            "incident": "stale_webhook",
        }

        other = by_recipient[other_admin_id]
        assert other.workspace_id == other_workspace_id
        assert other.metadata_json["provider"] == "slack"
        assert other.metadata_json["incident"] == "stale_webhook"

        rendered = str(
            [
                {
                    "title": value.title,
                    "body": value.body,
                    "metadata": value.metadata_json,
                }
                for value in notifications
            ]
        )
        for forbidden in (
            "private student message",
            "must-not-leak",
            "private stale error",
            "private-correlation-primary",
            "primary-stale-private-external-id",
            "other private message",
            "private-signature",
            "private-correlation-other",
        ):
            assert forbidden not in rendered

        raw = await session.get(RawWebhookEvent, primary_stale_id)
        assert raw is not None
        assert raw.processing_status == "received"
        assert raw.attempt_count == 0
        assert raw.processed_at is None


async def test_fresh_processed_and_unbound_webhooks_do_not_create_notifications(
    stale_webhook_notification_case,
) -> None:
    factory, tenant_id, _primary_workspace_id, _other_workspace_id, *_rest = (
        stale_webhook_notification_case
    )
    now = datetime(2026, 9, 12, 20, 0, tzinfo=UTC)

    async with factory() as session:
        stale_rows = list(
            await session.scalars(
                select(RawWebhookEvent).where(
                    RawWebhookEvent.tenant_id == tenant_id,
                    RawWebhookEvent.processing_status == "received",
                )
            )
        )
        for row in stale_rows:
            if row.correlation_id in {"private-correlation-primary", "private-correlation-other"}:
                row.processing_status = "processed"
                row.processed_at = now
        await session.commit()

    await channel_health_monitor._notify_stale_webhook_events(factory, now=now)

    async with factory() as session:
        assert list(await session.scalars(select(Notification))) == []


async def test_stale_notification_scan_failure_does_not_change_health_monitor_contract(
    stale_webhook_notification_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, *_rest = stale_webhook_notification_case

    async def no_due(_session: AsyncSession, *, now: datetime) -> list[tuple[UUID, UUID]]:
        del now
        return []

    async def fail_scan(
        _factory: async_sessionmaker[AsyncSession],
        *,
        now: datetime,
    ) -> None:
        del now
        raise RuntimeError("notification projection unavailable")

    monkeypatch.setattr(channel_health_monitor, "_due_connections", no_due)
    monkeypatch.setattr(channel_health_monitor, "_notify_stale_webhook_events", fail_scan)

    result = await channel_health_monitor.run_once(factory)

    assert result == {"due": 0, "checked": 0, "failed": 0}
