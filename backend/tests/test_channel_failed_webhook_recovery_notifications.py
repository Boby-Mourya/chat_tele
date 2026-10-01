from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from northstar_api.database import Base
from northstar_api.lead_crm.models import RawWebhookEvent
from northstar_api.models import Tenant, User, Workspace, WorkspaceMembership, WorkspaceRole
from northstar_api.notifications import Notification
from northstar_api.workers import channel_webhook_failure_notifications


@pytest.fixture
async def failed_webhook_recovery_case() -> AsyncIterator[
    tuple[
        async_sessionmaker[AsyncSession],
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
        tenant = Tenant(slug=f"failed-recovery-{uuid4().hex}", name="Failed webhook recovery")
        admin = User(
            email=f"failed-recovery-admin-{uuid4().hex}@example.test",
            name="Recovery Admin",
            password_hash="test-only",
            is_active=True,
        )
        manager = User(
            email=f"failed-recovery-manager-{uuid4().hex}@example.test",
            name="Recovery Manager",
            password_hash="test-only",
            is_active=True,
        )
        session.add_all([tenant, admin, manager])
        await session.flush()

        workspace = Workspace(
            tenant_id=tenant.id,
            name="Recovery workspace",
            slug=f"recovery-{uuid4().hex[:8]}",
            created_by=admin.id,
        )
        session.add(workspace)
        await session.flush()
        session.add_all(
            [
                WorkspaceMembership(
                    tenant_id=tenant.id,
                    workspace_id=workspace.id,
                    user_id=admin.id,
                    role=WorkspaceRole.ADMIN,
                ),
                WorkspaceMembership(
                    tenant_id=tenant.id,
                    workspace_id=workspace.id,
                    user_id=manager.id,
                    role=WorkspaceRole.MANAGER,
                ),
            ]
        )

        connection_id = uuid4()
        now = datetime(2026, 9, 12, 23, 0, tzinfo=UTC)
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
                connection_key=str(connection_id),
                provider="telegram",
                external_event_id=f"private-{name}-external-id",
                event_type="message.received",
                payload_json={"text": f"private {name} message", "token": f"secret-{name}"},
                headers_json={"authorization": f"Bearer secret-{name}"},
                payload_hash=(hex(index)[2:] * 64)[:64],
                verification_status="verified",
                processing_status=status,
                attempt_count=2,
                received_at=now - timedelta(minutes=30),
                processed_at=(
                    now - timedelta(minutes=1)
                    if status in {"processed", "ignored", "rejected"}
                    else None
                ),
                last_error=f"private {name} provider detail must not leak",
                correlation_id=f"private-{name}-correlation",
            )
            events[name] = value
            session.add(value)
        await session.flush()

        for name in ("processed", "ignored", "rejected", "failed", "received"):
            event = events[name]
            for recipient in (admin, manager):
                session.add(
                    Notification(
                        tenant_id=tenant.id,
                        workspace_id=workspace.id,
                        recipient_user_id=recipient.id,
                        category="channel",
                        severity="warning",
                        title="Channel webhook processing failed",
                        body="A webhook event failed during processing.",
                        action_url="/integrations",
                        action_label="Review webhook activity",
                        dedupe_key=f"channel-webhook-failed:{event.id}",
                        source_event_id=event.id,
                        metadata_json={
                            "rawEventId": str(event.id),
                            "processingStatus": "failed",
                        },
                    )
                )
        await session.commit()

        yield (
            factory,
            tenant.id,
            workspace.id,
            admin.id,
            manager.id,
            {name: value.id for name, value in events.items()},
        )

    await engine.dispose()


async def test_completed_failed_webhooks_emit_one_safe_recovery_per_recipient(
    failed_webhook_recovery_case,
) -> None:
    factory, _tenant_id, workspace_id, admin_id, manager_id, event_ids = (
        failed_webhook_recovery_case
    )

    await channel_webhook_failure_notifications.notify_failed_webhook_recoveries(factory)
    await channel_webhook_failure_notifications.notify_failed_webhook_recoveries(factory)

    async with factory() as session:
        recoveries = list(
            await session.scalars(
                select(Notification)
                .where(Notification.dedupe_key.like("channel-webhook-failed-recovery:%"))
                .order_by(Notification.source_event_id, Notification.recipient_user_id)
            )
        )
        assert len(recoveries) == 6
        by_event: dict[UUID, list[Notification]] = {}
        for value in recoveries:
            assert value.source_event_id is not None
            by_event.setdefault(value.source_event_id, []).append(value)

        for name in ("processed", "ignored", "rejected"):
            event_id = event_ids[name]
            values = by_event[event_id]
            assert {value.recipient_user_id for value in values} == {admin_id, manager_id}
            for value in values:
                assert value.workspace_id == workspace_id
                assert value.category == "channel"
                assert value.severity == "info"
                assert value.title == "Channel webhook processing recovered"
                assert value.action_url == "/integrations"
                assert value.action_label == "Review webhook activity"
                assert value.dedupe_key == f"channel-webhook-failed-recovery:{event_id}"
                assert value.metadata_json == {
                    "rawEventId": str(event_id),
                    "connectionId": value.metadata_json["connectionId"],
                    "provider": "telegram",
                    "finalStatus": name,
                    "transition": "recovery",
                    "incident": "webhook_processing_failed",
                }

        assert event_ids["failed"] not in by_event
        assert event_ids["received"] not in by_event
        assert event_ids["no_incident"] not in by_event

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
            "private-processed-external-id",
            "private-ignored-external-id",
            "private-rejected-external-id",
            "private-processed-correlation",
            "private-ignored-correlation",
            "private-rejected-correlation",
            "private processed provider detail",
            "private ignored provider detail",
            "private rejected provider detail",
        ):
            assert forbidden not in rendered

        for name, expected_status in statuses_for_assertion().items():
            raw = await session.get(RawWebhookEvent, event_ids[name])
            assert raw is not None
            assert raw.processing_status == expected_status

        assert await channel_webhook_failure_notifications.failed_webhook_recovery_candidates(
            session
        ) == []


def statuses_for_assertion() -> dict[str, str]:
    return {
        "processed": "processed",
        "ignored": "ignored",
        "rejected": "rejected",
        "failed": "failed",
        "received": "received",
        "no_incident": "processed",
    }


async def test_recovery_requires_a_prior_failed_incident(failed_webhook_recovery_case) -> None:
    factory, _tenant_id, _workspace_id, _admin_id, _manager_id, event_ids = (
        failed_webhook_recovery_case
    )

    await channel_webhook_failure_notifications.notify_failed_webhook_recoveries(factory)

    async with factory() as session:
        no_incident_recovery = await session.scalar(
            select(Notification.id).where(
                Notification.dedupe_key
                == f"channel-webhook-failed-recovery:{event_ids['no_incident']}"
            )
        )
        assert no_incident_recovery is None


async def test_failed_recovery_scan_failure_is_isolated_from_incident_projection(
    failed_webhook_recovery_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, *_rest = failed_webhook_recovery_case

    async def no_failed(_session: AsyncSession) -> list[tuple[UUID, UUID, UUID]]:
        return []

    async def fail_recovery(_factory: async_sessionmaker[AsyncSession]) -> None:
        raise RuntimeError("recovery notification projection unavailable")

    monkeypatch.setattr(channel_webhook_failure_notifications, "failed_webhook_events", no_failed)
    monkeypatch.setattr(
        channel_webhook_failure_notifications,
        "notify_failed_webhook_recoveries",
        fail_recovery,
    )

    await channel_webhook_failure_notifications.notify_failed_webhook_events(factory)
