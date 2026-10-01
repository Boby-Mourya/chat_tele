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
from northstar_api.workers.channel_webhook_failure_notifications import (
    failed_webhook_events,
    notify_failed_webhook_events,
)


@pytest.fixture
async def failed_webhook_notification_case() -> AsyncIterator[
    tuple[
        async_sessionmaker[AsyncSession],
        UUID,
        UUID,
        UUID,
        UUID,
        UUID,
        dict[str, UUID],
    ]
]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        tenant = Tenant(slug=f"failed-webhook-{uuid4().hex}", name="Failed webhook tenant")
        primary_admin = User(
            email=f"failed-primary-{uuid4().hex}@example.test",
            name="Primary Admin",
            password_hash="not-used-by-this-test",
            is_active=True,
        )
        other_admin = User(
            email=f"failed-other-{uuid4().hex}@example.test",
            name="Other Admin",
            password_hash="not-used-by-this-test",
            is_active=True,
        )
        session.add_all([tenant, primary_admin, other_admin])
        await session.flush()

        primary_workspace = Workspace(
            tenant_id=tenant.id,
            name="Primary failed webhook workspace",
            slug=f"primary-failed-{uuid4().hex[:8]}",
            created_by=primary_admin.id,
        )
        other_workspace = Workspace(
            tenant_id=tenant.id,
            name="Other failed webhook workspace",
            slug=f"other-failed-{uuid4().hex[:8]}",
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
                    role=WorkspaceRole.MANAGER,
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

        now = datetime(2026, 9, 12, 22, 0, tzinfo=UTC)
        events: dict[str, RawWebhookEvent] = {
            "primary_failed": RawWebhookEvent(
                tenant_id=tenant.id,
                connection_key=str(primary_connection.id),
                provider="telegram",
                external_event_id="private-primary-failed-external",
                event_type="message.received",
                payload_json={"text": "private primary message", "token": "must-not-leak"},
                headers_json={"authorization": "Bearer must-not-leak"},
                payload_hash="a" * 64,
                verification_status="verified",
                processing_status="failed",
                attempt_count=3,
                received_at=now - timedelta(minutes=30),
                last_error="private provider failure token=must-not-leak",
                correlation_id="private-primary-correlation",
            ),
            "other_failed": RawWebhookEvent(
                tenant_id=tenant.id,
                connection_key=str(other_connection.id),
                provider="slack",
                external_event_id="private-other-failed-external",
                event_type="message.received",
                payload_json={"text": "private other message"},
                headers_json={"x-slack-signature": "private-signature"},
                payload_hash="b" * 64,
                verification_status="verified",
                processing_status="failed",
                attempt_count=2,
                received_at=now - timedelta(minutes=20),
                last_error="private slack processing detail",
                correlation_id="private-other-correlation",
            ),
            "unbound_failed": RawWebhookEvent(
                tenant_id=tenant.id,
                connection_key=str(unbound_connection.id),
                provider="instagram",
                external_event_id="unbound-failed",
                event_type="message.received",
                payload_json={"text": "unbound private message"},
                headers_json={},
                payload_hash="c" * 64,
                verification_status="verified",
                processing_status="failed",
                attempt_count=1,
                received_at=now - timedelta(minutes=40),
                correlation_id="unbound-private-correlation",
            ),
            "processed": RawWebhookEvent(
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
                received_at=now - timedelta(minutes=50),
                processed_at=now - timedelta(minutes=49),
                correlation_id="processed-private-correlation",
            ),
        }
        session.add_all(events.values())
        await session.commit()
        for value in events.values():
            await session.refresh(value)

        yield (
            factory,
            tenant.id,
            primary_workspace.id,
            other_workspace.id,
            primary_admin.id,
            other_admin.id,
            {name: value.id for name, value in events.items()},
        )

    await engine.dispose()


async def test_failed_webhooks_notify_only_their_workspace_once_and_remain_secret_safe(
    failed_webhook_notification_case,
) -> None:
    (
        factory,
        _tenant_id,
        primary_workspace_id,
        other_workspace_id,
        primary_admin_id,
        other_admin_id,
        event_ids,
    ) = failed_webhook_notification_case

    await notify_failed_webhook_events(factory)
    await notify_failed_webhook_events(factory)

    async with factory() as session:
        notifications = list(
            await session.scalars(
                select(Notification)
                .where(Notification.dedupe_key.like("channel-webhook-failed:%"))
                .order_by(Notification.recipient_user_id)
            )
        )
        assert len(notifications) == 2
        by_recipient = {value.recipient_user_id: value for value in notifications}

        primary = by_recipient[primary_admin_id]
        assert primary.workspace_id == primary_workspace_id
        assert primary.source_event_id == event_ids["primary_failed"]
        assert primary.category == "channel"
        assert primary.severity == "warning"
        assert primary.title == "Channel webhook processing failed"
        assert primary.action_url == "/integrations"
        assert primary.action_label == "Review webhook activity"
        assert primary.dedupe_key == f"channel-webhook-failed:{event_ids['primary_failed']}"
        assert primary.metadata_json == {
            "rawEventId": str(event_ids["primary_failed"]),
            "connectionId": primary.metadata_json["connectionId"],
            "provider": "telegram",
            "processingStatus": "failed",
            "errorCode": "processing_failed",
            "incident": "webhook_processing_failed",
        }

        other = by_recipient[other_admin_id]
        assert other.workspace_id == other_workspace_id
        assert other.source_event_id == event_ids["other_failed"]
        assert other.metadata_json["provider"] == "slack"

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
            "private primary message",
            "private other message",
            "must-not-leak",
            "private-signature",
            "private provider failure",
            "private slack processing detail",
            "private-primary-correlation",
            "private-other-correlation",
            "private-primary-failed-external",
            "private-other-failed-external",
        ):
            assert forbidden not in rendered

        for name, expected_status in (
            ("primary_failed", "failed"),
            ("other_failed", "failed"),
            ("unbound_failed", "failed"),
            ("processed", "processed"),
        ):
            raw = await session.get(RawWebhookEvent, event_ids[name])
            assert raw is not None
            assert raw.processing_status == expected_status

        assert await failed_webhook_events(session) == []


async def test_unbound_and_nonfailed_webhooks_are_not_selected(
    failed_webhook_notification_case,
) -> None:
    factory, _tenant_id, *_rest = failed_webhook_notification_case

    async with factory() as session:
        selected = await failed_webhook_events(session)

    assert len(selected) == 2


async def test_failed_webhook_notification_scan_failure_does_not_change_health_monitor_contract(
    failed_webhook_notification_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, *_rest = failed_webhook_notification_case

    async def no_due(_session: AsyncSession, *, now: datetime) -> list[tuple[UUID, UUID]]:
        del now
        return []

    async def no_stale_scan(
        _factory: async_sessionmaker[AsyncSession],
        *,
        now: datetime,
    ) -> None:
        del now

    async def no_recovery_scan(_factory: async_sessionmaker[AsyncSession]) -> None:
        return None

    async def fail_failed_scan(_factory: async_sessionmaker[AsyncSession]) -> None:
        raise RuntimeError("failed-webhook notification projection unavailable")

    monkeypatch.setattr(channel_health_monitor, "_due_connections", no_due)
    monkeypatch.setattr(channel_health_monitor, "_notify_stale_webhook_events", no_stale_scan)
    monkeypatch.setattr(channel_health_monitor, "_notify_stale_webhook_recoveries", no_recovery_scan)
    monkeypatch.setattr(channel_health_monitor, "notify_failed_webhook_events", fail_failed_scan)

    result = await channel_health_monitor.run_once(factory)

    assert result == {"due": 0, "checked": 0, "failed": 0}
