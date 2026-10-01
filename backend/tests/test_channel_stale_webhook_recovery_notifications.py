from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from northstar_api.database import Base
from northstar_api.lead_crm.channel_models import ChannelConnection
from northstar_api.lead_crm.models import RawWebhookEvent
from northstar_api.models import Tenant, User, Workspace, WorkspaceMembership, WorkspaceRole
from northstar_api.notifications import Notification
from northstar_api.workers import channel_health_monitor


@pytest.fixture
async def stale_webhook_recovery_case() -> AsyncIterator[
    tuple[async_sessionmaker[AsyncSession], UUID, UUID, UUID, dict[str, UUID]]
]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        tenant = Tenant(slug=f"stale-recovery-{uuid4().hex}", name="Stale recovery tenant")
        admin = User(
            email=f"stale-recovery-admin-{uuid4().hex}@example.test",
            name="Recovery Admin",
            password_hash="not-used-by-this-test",
            is_active=True,
        )
        session.add_all([tenant, admin])
        await session.flush()
        workspace = Workspace(
            tenant_id=tenant.id,
            name="Recovery workspace",
            slug=f"recovery-{uuid4().hex[:8]}",
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
        connection = ChannelConnection(
            tenant_id=tenant.id,
            provider="telegram",
            name="Recovery Telegram",
            status="healthy",
            configuration_json={},
        )
        session.add(connection)
        await session.flush()

        now = datetime(2026, 9, 12, 21, 0, tzinfo=UTC)
        statuses = {
            "processed": "processed",
            "ignored": "ignored",
            "rejected": "rejected",
            "failed": "failed",
            "received": "received",
            "no_incident": "processed",
        }
        events: dict[str, RawWebhookEvent] = {}
        for index, (name, status) in enumerate(statuses.items(), start=1):
            value = RawWebhookEvent(
                tenant_id=tenant.id,
                connection_key=str(connection.id),
                provider="telegram",
                external_event_id=f"private-{name}-external-id",
                event_type="message.received",
                payload_json={"text": f"private {name} message", "secret": f"secret-{name}"},
                headers_json={"authorization": f"Bearer secret-{name}"},
                payload_hash=(hex(index)[2:] * 64)[:64],
                verification_status="verified",
                processing_status=status,
                attempt_count=1 if status != "received" else 0,
                received_at=now - timedelta(minutes=20),
                processed_at=(
                    now - timedelta(minutes=1)
                    if status in {"processed", "ignored", "rejected"}
                    else None
                ),
                last_error=f"private {name} error must not leak",
                correlation_id=f"private-{name}-correlation",
            )
            events[name] = value
            session.add(value)
        await session.flush()

        for name in ("processed", "ignored", "rejected", "failed", "received"):
            event = events[name]
            session.add(
                Notification(
                    tenant_id=tenant.id,
                    workspace_id=workspace.id,
                    recipient_user_id=admin.id,
                    category="channel",
                    severity="warning",
                    title="Channel webhook processing is delayed",
                    body="A webhook event is delayed.",
                    action_url="/integrations",
                    action_label="Review webhook activity",
                    dedupe_key=f"channel-webhook-stale:{event.id}",
                    metadata_json={"rawEventId": str(event.id)},
                )
            )
        await session.commit()

        yield (
            factory,
            tenant.id,
            workspace.id,
            admin.id,
            {name: value.id for name, value in events.items()},
        )

    await engine.dispose()


async def test_completed_stale_webhooks_emit_one_safe_recovery_notification(
    stale_webhook_recovery_case,
) -> None:
    factory, _tenant_id, workspace_id, admin_id, event_ids = stale_webhook_recovery_case

    await channel_health_monitor._notify_stale_webhook_recoveries(factory)
    await channel_health_monitor._notify_stale_webhook_recoveries(factory)

    async with factory() as session:
        recoveries = list(
            await session.scalars(
                select(Notification)
                .where(Notification.dedupe_key.like("channel-webhook-stale-recovery:%"))
                .order_by(Notification.dedupe_key)
            )
        )
        assert len(recoveries) == 3
        by_event = {value.metadata_json["rawEventId"]: value for value in recoveries}

        for name in ("processed", "ignored", "rejected"):
            event_id = event_ids[name]
            value = by_event[str(event_id)]
            assert value.workspace_id == workspace_id
            assert value.recipient_user_id == admin_id
            assert value.category == "channel"
            assert value.severity == "info"
            assert value.title == "Channel webhook processing recovered"
            assert value.action_url == "/integrations"
            assert value.action_label == "Review webhook activity"
            assert value.dedupe_key == f"channel-webhook-stale-recovery:{event_id}"
            assert value.metadata_json["rawEventId"] == str(event_id)
            assert value.metadata_json["provider"] == "telegram"
            assert value.metadata_json["finalStatus"] == name
            assert value.metadata_json["transition"] == "recovery"

        assert str(event_ids["failed"]) not in by_event
        assert str(event_ids["received"]) not in by_event
        assert str(event_ids["no_incident"]) not in by_event

        rendered = str(
            [
                {
                    "title": value.title,
                    "body": value.body,
                    "metadata": value.metadata_json,
                }
                for value in recoveries
            ]
        )
        for forbidden in (
            "secret-processed",
            "secret-ignored",
            "secret-rejected",
            "private processed message",
            "private ignored message",
            "private rejected message",
            "private-processed-correlation",
            "private-ignored-correlation",
            "private-rejected-correlation",
            "private-processed-external-id",
            "private-ignored-external-id",
            "private-rejected-external-id",
            "private processed error",
            "private ignored error",
            "private rejected error",
        ):
            assert forbidden not in rendered

        for name, expected_status in (
            ("processed", "processed"),
            ("ignored", "ignored"),
            ("rejected", "rejected"),
            ("failed", "failed"),
            ("received", "received"),
        ):
            raw = await session.get(RawWebhookEvent, event_ids[name])
            assert raw is not None
            assert raw.processing_status == expected_status


async def test_recovery_scan_failure_does_not_change_health_monitor_contract(
    stale_webhook_recovery_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, *_rest = stale_webhook_recovery_case

    async def no_due(_session: AsyncSession, *, now: datetime) -> list[tuple[UUID, UUID]]:
        del now
        return []

    async def no_incident_scan(
        _factory: async_sessionmaker[AsyncSession],
        *,
        now: datetime,
    ) -> None:
        del now

    async def fail_recovery_scan(_factory: async_sessionmaker[AsyncSession]) -> None:
        raise RuntimeError("recovery notification projection unavailable")

    monkeypatch.setattr(channel_health_monitor, "_due_connections", no_due)
    monkeypatch.setattr(channel_health_monitor, "_notify_stale_webhook_events", no_incident_scan)
    monkeypatch.setattr(channel_health_monitor, "_notify_stale_webhook_recoveries", fail_recovery_scan)

    result = await channel_health_monitor.run_once(factory)

    assert result == {"due": 0, "checked": 0, "failed": 0}
