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
from northstar_api.lead_crm.channels import ChannelConnectionContext
from northstar_api.lead_crm.domain import ChannelProvider
from northstar_api.models import Tenant, User, Workspace, WorkspaceMembership, WorkspaceRole
from northstar_api.notifications import Notification
from northstar_api.workers import channel_health_monitor


@pytest.fixture
async def incident_case() -> AsyncIterator[
    tuple[async_sessionmaker[AsyncSession], UUID, UUID, UUID, ChannelConnection]
]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        tenant = Tenant(slug=f"channel-alert-{uuid4().hex}", name="Channel alert tenant")
        admin = User(
            email=f"channel-admin-{uuid4().hex}@example.test",
            name="Channel Admin",
            password_hash="not-used-by-this-test",
            is_active=True,
        )
        session.add_all([tenant, admin])
        await session.flush()
        workspace = Workspace(
            tenant_id=tenant.id,
            name="Messaging Operations",
            slug=f"messaging-ops-{uuid4().hex}",
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
        channel = ChannelConnection(
            tenant_id=tenant.id,
            provider=ChannelProvider.TELEGRAM.value,
            name="Student Telegram",
            status="configured",
            configuration_json={},
            last_health_at=datetime.now(UTC) - timedelta(minutes=10),
        )
        session.add(channel)
        await session.flush()
        session.add(
            WorkspaceChannelConnection(
                tenant_id=tenant.id,
                workspace_id=workspace.id,
                agent_id=None,
                connection_id=channel.id,
            )
        )
        await session.commit()
        await session.refresh(channel)
        yield factory, tenant.id, workspace.id, admin.id, channel

    await engine.dispose()


def _install_health_result(
    monkeypatch: pytest.MonkeyPatch,
    *,
    status_box: dict[str, str],
) -> None:
    class Connector:
        async def health_check(self, context: ChannelConnectionContext) -> dict[str, str]:
            assert context.provider == ChannelProvider.TELEGRAM
            return {
                "status": status_box["value"],
                "username": "must-not-enter-notifications",
                "access_token": "must-not-enter-notifications",
            }

    monkeypatch.setattr(channel_health_monitor.channel_registry, "get", lambda _provider: Connector())


def test_channel_health_transition_only_alerts_on_incident_boundary_and_recovery() -> None:
    assert channel_health_monitor._health_transition("configured", "unhealthy") == "incident"
    assert channel_health_monitor._health_transition("unknown", "auth_required") == "incident"
    assert channel_health_monitor._health_transition("unhealthy", "auth_required") is None
    assert channel_health_monitor._health_transition("rate_limited", "degraded") is None
    assert channel_health_monitor._health_transition("auth_required", "healthy") == "recovery"
    assert channel_health_monitor._health_transition("healthy", "healthy") is None


async def test_monitor_notifies_workspace_admin_only_on_incident_and_recovery(
    incident_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, tenant_id, workspace_id, admin_id, channel = incident_case
    status_box = {"value": "unhealthy"}
    _install_health_result(monkeypatch, status_box=status_box)

    first_check = datetime(2026, 9, 12, 17, 0, tzinfo=UTC)
    assert await channel_health_monitor.monitor_connection(
        factory,
        tenant_id=tenant_id,
        connection_id=channel.id,
        now=first_check,
    ) is True

    status_box["value"] = "auth_required"
    assert await channel_health_monitor.monitor_connection(
        factory,
        tenant_id=tenant_id,
        connection_id=channel.id,
        now=first_check + timedelta(minutes=10),
    ) is True

    status_box["value"] = "healthy"
    assert await channel_health_monitor.monitor_connection(
        factory,
        tenant_id=tenant_id,
        connection_id=channel.id,
        now=first_check + timedelta(minutes=20),
    ) is True

    assert await channel_health_monitor.monitor_connection(
        factory,
        tenant_id=tenant_id,
        connection_id=channel.id,
        now=first_check + timedelta(minutes=30),
    ) is True

    async with factory() as session:
        notifications = list(await session.scalars(select(Notification)))
        assert len(notifications) == 2
        by_title = {value.title: value for value in notifications}
        incident = by_title["Channel connection needs attention"]
        recovery = by_title["Channel connection recovered"]

        assert incident.workspace_id == workspace_id
        assert incident.recipient_user_id == admin_id
        assert incident.category == "channel"
        assert incident.severity == "warning"
        assert incident.action_url == "/integrations"
        assert incident.action_label == "Review channel health"
        assert incident.metadata_json == {
            "connectionId": str(channel.id),
            "provider": "telegram",
            "previousStatus": "configured",
            "currentStatus": "unhealthy",
            "transition": "incident",
        }
        assert "must-not-enter-notifications" not in str(incident.metadata_json)
        assert "must-not-enter-notifications" not in incident.body

        assert recovery.workspace_id == workspace_id
        assert recovery.recipient_user_id == admin_id
        assert recovery.category == "channel"
        assert recovery.severity == "info"
        assert recovery.metadata_json["previousStatus"] == "auth_required"
        assert recovery.metadata_json["currentStatus"] == "healthy"
        assert recovery.metadata_json["transition"] == "recovery"
        assert incident.dedupe_key != recovery.dedupe_key


async def test_unbound_channel_keeps_health_update_without_notification(
    incident_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, tenant_id, _workspace_id, _admin_id, channel = incident_case
    status_box = {"value": "unhealthy"}
    _install_health_result(monkeypatch, status_box=status_box)

    async with factory() as session:
        await session.execute(
            delete(WorkspaceChannelConnection).where(
                WorkspaceChannelConnection.connection_id == channel.id,
                WorkspaceChannelConnection.tenant_id == tenant_id,
            )
        )
        await session.commit()

    checked_at = datetime(2026, 9, 12, 18, 0, tzinfo=UTC)
    assert await channel_health_monitor.monitor_connection(
        factory,
        tenant_id=tenant_id,
        connection_id=channel.id,
        now=checked_at,
    ) is True

    async with factory() as session:
        refreshed = await session.get(ChannelConnection, channel.id)
        assert refreshed is not None
        assert refreshed.status == "unhealthy"
        assert refreshed.last_health_at is not None
        assert list(await session.scalars(select(Notification))) == []


async def test_notification_failure_does_not_rollback_channel_health_update(
    incident_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, tenant_id, _workspace_id, _admin_id, channel = incident_case
    status_box = {"value": "unhealthy"}
    _install_health_result(monkeypatch, status_box=status_box)

    async def fail_notification(*_args, **_kwargs) -> int:
        raise RuntimeError("notification store unavailable")

    monkeypatch.setattr(channel_health_monitor, "_notify_health_transition", fail_notification)
    checked_at = datetime(2026, 9, 12, 19, 0, tzinfo=UTC)

    assert await channel_health_monitor.monitor_connection(
        factory,
        tenant_id=tenant_id,
        connection_id=channel.id,
        now=checked_at,
    ) is True

    async with factory() as session:
        refreshed = await session.get(ChannelConnection, channel.id)
        assert refreshed is not None
        assert refreshed.status == "unhealthy"
        assert refreshed.last_error == "Scheduled channel health check reported unhealthy"
        assert refreshed.last_health_at is not None
