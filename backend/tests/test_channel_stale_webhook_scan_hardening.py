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
async def stale_scan_case() -> AsyncIterator[
    tuple[
        async_sessionmaker[AsyncSession],
        UUID,
        UUID,
        UUID,
        UUID,
        datetime,
    ]
]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        tenant = Tenant(slug=f"stale-scan-{uuid4().hex}", name="Stale scan tenant")
        admin = User(
            email=f"stale-scan-admin-{uuid4().hex}@example.test",
            name="Stale Scan Admin",
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

        connection = ChannelConnection(
            tenant_id=tenant.id,
            provider="telegram",
            name="Bound Telegram",
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
        session.add_all([connection, unbound_connection])
        await session.flush()
        session.add(
            WorkspaceChannelConnection(
                tenant_id=tenant.id,
                workspace_id=workspace.id,
                agent_id=None,
                connection_id=connection.id,
            )
        )
        await session.commit()

        now = datetime(2026, 9, 13, 0, 0, tzinfo=UTC)
        yield factory, tenant.id, workspace.id, admin.id, connection.id, now

    await engine.dispose()


def _raw_event(
    *,
    tenant_id: UUID,
    connection_id: UUID,
    name: str,
    received_at: datetime,
    status: str = "received",
) -> RawWebhookEvent:
    return RawWebhookEvent(
        tenant_id=tenant_id,
        connection_key=str(connection_id),
        provider="telegram",
        external_event_id=f"external-{name}",
        event_type="message.received",
        payload_json={"text": f"private {name} message", "token": f"secret-{name}"},
        headers_json={"authorization": f"Bearer secret-{name}"},
        payload_hash=(name[0] * 64)[:64],
        verification_status="verified",
        processing_status=status,
        attempt_count=0,
        received_at=received_at,
        processed_at=received_at + timedelta(minutes=1) if status != "received" else None,
        last_error=f"private {name} detail",
        correlation_id=f"private-{name}-correlation",
    )


async def test_stale_scan_skips_legacy_alerted_and_unbound_rows_before_batch_limit(
    stale_scan_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, tenant_id, workspace_id, admin_id, connection_id, now = stale_scan_case
    monkeypatch.setattr(channel_health_monitor, "STALE_WEBHOOK_SCAN_PAGE_SIZE", 2)
    monkeypatch.setattr(channel_health_monitor, "STALE_WEBHOOK_BATCH_SIZE", 1)

    async with factory() as session:
        unbound_connection = ChannelConnection(
            tenant_id=tenant_id,
            provider="instagram",
            name="Older unbound connection",
            status="healthy",
            configuration_json={},
        )
        session.add(unbound_connection)
        await session.flush()

        unbound = _raw_event(
            tenant_id=tenant_id,
            connection_id=unbound_connection.id,
            name="unbound",
            received_at=now - timedelta(minutes=40),
        )
        legacy_one = _raw_event(
            tenant_id=tenant_id,
            connection_id=connection_id,
            name="legacy-one",
            received_at=now - timedelta(minutes=30),
        )
        legacy_two = _raw_event(
            tenant_id=tenant_id,
            connection_id=connection_id,
            name="legacy-two",
            received_at=now - timedelta(minutes=20),
        )
        target = _raw_event(
            tenant_id=tenant_id,
            connection_id=connection_id,
            name="target",
            received_at=now - timedelta(minutes=10),
        )
        session.add_all([unbound, legacy_one, legacy_two, target])
        await session.flush()

        for legacy in (legacy_one, legacy_two):
            session.add(
                Notification(
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    recipient_user_id=admin_id,
                    category="channel",
                    severity="warning",
                    title="Channel webhook processing is delayed",
                    body="Legacy stale alert",
                    action_url="/integrations",
                    action_label="Review webhook activity",
                    dedupe_key=f"channel-webhook-stale:{legacy.id}",
                    source_event_id=None,
                    metadata_json={"rawEventId": str(legacy.id)},
                )
            )
        await session.commit()
        target_id = target.id

    async with factory() as session:
        candidates = await channel_health_monitor._stale_webhook_events(session, now=now)
    assert candidates == [(target_id, tenant_id, connection_id)]

    await channel_health_monitor._notify_stale_webhook_events(factory, now=now)

    async with factory() as session:
        target_notification = await session.scalar(
            select(Notification).where(
                Notification.dedupe_key == f"channel-webhook-stale:{target_id}"
            )
        )
        assert target_notification is not None
        assert target_notification.source_event_id == target_id

        raw = await session.get(RawWebhookEvent, target_id)
        assert raw is not None
        assert raw.processing_status == "received"
        assert raw.attempt_count == 0
        assert raw.processed_at is None


async def test_stale_recovery_scan_pages_past_recovered_and_unresolved_incidents(
    stale_scan_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, tenant_id, workspace_id, admin_id, connection_id, now = stale_scan_case
    monkeypatch.setattr(channel_health_monitor, "STALE_WEBHOOK_RECOVERY_PAGE_SIZE", 2)
    monkeypatch.setattr(channel_health_monitor, "STALE_WEBHOOK_RECOVERY_SCAN_SIZE", 1)

    async with factory() as session:
        target = _raw_event(
            tenant_id=tenant_id,
            connection_id=connection_id,
            name="old-target",
            received_at=now - timedelta(minutes=40),
            status="processed",
        )
        already_recovered = _raw_event(
            tenant_id=tenant_id,
            connection_id=connection_id,
            name="already-recovered",
            received_at=now - timedelta(minutes=30),
            status="processed",
        )
        unresolved = _raw_event(
            tenant_id=tenant_id,
            connection_id=connection_id,
            name="unresolved",
            received_at=now - timedelta(minutes=20),
            status="received",
        )
        session.add_all([target, already_recovered, unresolved])
        await session.flush()

        target_created = now - timedelta(minutes=15)
        recovered_created = now - timedelta(minutes=10)
        unresolved_created = now - timedelta(minutes=5)
        session.add_all(
            [
                Notification(
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    recipient_user_id=admin_id,
                    category="channel",
                    severity="warning",
                    title="Channel webhook processing is delayed",
                    body="Legacy target incident",
                    action_url="/integrations",
                    action_label="Review webhook activity",
                    dedupe_key=f"channel-webhook-stale:{target.id}",
                    source_event_id=None,
                    metadata_json={"rawEventId": str(target.id)},
                    created_at=target_created,
                ),
                Notification(
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    recipient_user_id=admin_id,
                    category="channel",
                    severity="warning",
                    title="Channel webhook processing is delayed",
                    body="Recovered incident",
                    action_url="/integrations",
                    action_label="Review webhook activity",
                    dedupe_key=f"channel-webhook-stale:{already_recovered.id}",
                    source_event_id=already_recovered.id,
                    metadata_json={"rawEventId": str(already_recovered.id)},
                    created_at=recovered_created,
                ),
                Notification(
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    recipient_user_id=admin_id,
                    category="channel",
                    severity="info",
                    title="Channel webhook processing recovered",
                    body="Recovered",
                    action_url="/integrations",
                    action_label="Review webhook activity",
                    dedupe_key=f"channel-webhook-stale-recovery:{already_recovered.id}",
                    source_event_id=None,
                    metadata_json={"rawEventId": str(already_recovered.id)},
                    created_at=recovered_created + timedelta(seconds=1),
                ),
                Notification(
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    recipient_user_id=admin_id,
                    category="channel",
                    severity="warning",
                    title="Channel webhook processing is delayed",
                    body="Unresolved incident",
                    action_url="/integrations",
                    action_label="Review webhook activity",
                    dedupe_key=f"channel-webhook-stale:{unresolved.id}",
                    source_event_id=unresolved.id,
                    metadata_json={"rawEventId": str(unresolved.id)},
                    created_at=unresolved_created,
                ),
            ]
        )
        await session.commit()
        target_id = target.id

    async with factory() as session:
        candidates = await channel_health_monitor._stale_webhook_recovery_candidates(session)
    assert candidates == [(tenant_id, workspace_id, target_id)]

    await channel_health_monitor._notify_stale_webhook_recoveries(factory)

    async with factory() as session:
        recovery = await session.scalar(
            select(Notification).where(
                Notification.dedupe_key == f"channel-webhook-stale-recovery:{target_id}"
            )
        )
        assert recovery is not None
        assert recovery.source_event_id == target_id
        assert recovery.metadata_json["finalStatus"] == "processed"
        assert recovery.metadata_json["transition"] == "recovery"

        raw = await session.get(RawWebhookEvent, target_id)
        assert raw is not None
        assert raw.processing_status == "processed"
