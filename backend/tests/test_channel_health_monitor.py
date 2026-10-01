from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from northstar_api.database import Base
from northstar_api.lead_crm.channel_models import ChannelConnection
from northstar_api.lead_crm.channels import ChannelConnectionContext
from northstar_api.lead_crm.credentials import CredentialStoreError
from northstar_api.lead_crm.domain import ChannelProvider
from northstar_api.models import Tenant
from northstar_api.workers import channel_health_monitor


@pytest.fixture
async def channel_case() -> AsyncIterator[
    tuple[async_sessionmaker[AsyncSession], UUID, ChannelConnection]
]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        tenant = Tenant(slug=f"channel-health-{uuid4().hex}", name="Channel health tenant")
        session.add(tenant)
        await session.flush()
        channel = ChannelConnection(
            tenant_id=tenant.id,
            provider=ChannelProvider.TELEGRAM.value,
            name="Academy Telegram",
            status="configured",
            configuration_json={"webhookMode": "managed"},
            last_health_at=datetime(2026, 9, 12, 15, 50, tzinfo=UTC),
            last_error="old error",
        )
        session.add(channel)
        await session.commit()
        await session.refresh(channel)
        yield factory, tenant.id, channel

    await engine.dispose()


async def test_due_channel_health_check_updates_existing_health_fields(
    channel_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, tenant_id, channel = channel_case
    checked_at = datetime(2026, 9, 12, 16, 0, tzinfo=UTC)

    class HealthyConnector:
        async def health_check(self, context: ChannelConnectionContext) -> dict[str, str]:
            assert context.connection_id == channel.id
            assert context.provider == ChannelProvider.TELEGRAM
            return {
                "status": "healthy",
                "username": "academy_bot",
                "access_token": "must-not-be-persisted",
            }

    monkeypatch.setattr(channel_health_monitor.channel_registry, "get", lambda _provider: HealthyConnector())

    assert await channel_health_monitor.monitor_connection(
        factory,
        tenant_id=tenant_id,
        connection_id=channel.id,
        now=checked_at,
    ) is True

    async with factory() as session:
        refreshed = await session.get(ChannelConnection, channel.id)
        assert refreshed is not None
        assert refreshed.status == "healthy"
        assert refreshed.last_error is None
        assert refreshed.last_health_at is not None
        value = refreshed.last_health_at
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        assert value == checked_at
        assert "academy_bot" not in str(refreshed.configuration_json)
        assert "must-not-be-persisted" not in str(refreshed.configuration_json)


async def test_unhealthy_result_records_normalized_failure_without_provider_details(
    channel_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, tenant_id, channel = channel_case
    checked_at = datetime(2026, 9, 12, 16, 10, tzinfo=UTC)

    class UnhealthyConnector:
        async def health_check(self, _context: ChannelConnectionContext) -> dict[str, str]:
            return {
                "status": "unhealthy",
                "providerError": "token=must-not-be-stored",
            }

    monkeypatch.setattr(channel_health_monitor.channel_registry, "get", lambda _provider: UnhealthyConnector())

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
        assert "must-not-be-stored" not in refreshed.last_error
        assert refreshed.last_failure_at is not None


async def test_repeated_transient_failures_preserve_failure_episode_start(channel_case) -> None:
    _factory, _tenant_id, channel = channel_case
    failure_started_at = datetime(2026, 9, 12, 16, 0, tzinfo=UTC)
    next_check_at = failure_started_at + timedelta(minutes=2)
    channel.status = "unhealthy"
    channel.last_failure_at = failure_started_at

    channel_health_monitor._record_status(
        channel,
        status="unhealthy",
        checked_at=next_check_at,
    )

    assert channel.last_failure_at == failure_started_at
    assert channel.last_health_at == next_check_at


async def test_unreadable_credentials_require_reconnection_without_exposing_error(
    channel_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, tenant_id, channel = channel_case
    checked_at = datetime(2026, 9, 12, 16, 20, tzinfo=UTC)
    async with factory() as session:
        stored = await session.get(ChannelConnection, channel.id)
        assert stored is not None
        stored.credentials_encrypted = b"unreadable"
        await session.commit()

    def fail_decrypt(_value: bytes) -> dict[str, object]:
        raise CredentialStoreError("stored token and secret were invalid")

    called = False

    def unexpected_connector(_provider: ChannelProvider):
        nonlocal called
        called = True
        raise AssertionError("connector must not run with unreadable credentials")

    monkeypatch.setattr(channel_health_monitor.credential_store, "decrypt", fail_decrypt)
    monkeypatch.setattr(channel_health_monitor.channel_registry, "get", unexpected_connector)

    assert await channel_health_monitor.monitor_connection(
        factory,
        tenant_id=tenant_id,
        connection_id=channel.id,
        now=checked_at,
    ) is True

    assert called is False
    async with factory() as session:
        refreshed = await session.get(ChannelConnection, channel.id)
        assert refreshed is not None
        assert refreshed.status == "auth_required"
        assert refreshed.last_error == "Scheduled channel health check failed: credential_error"
        assert "token" not in refreshed.last_error
        assert "secret" not in refreshed.last_error


async def test_due_selection_excludes_recent_draft_and_disabled_channels(channel_case) -> None:
    factory, tenant_id, channel = channel_case
    now = datetime.now(UTC)
    async with factory() as session:
        due = await session.get(ChannelConnection, channel.id)
        assert due is not None
        due.last_health_at = now - timedelta(minutes=10)
        session.add_all(
            [
                ChannelConnection(
                    tenant_id=tenant_id,
                    provider=ChannelProvider.SLACK.value,
                    name="Recent Slack",
                    status="healthy",
                    configuration_json={},
                    last_health_at=now - timedelta(seconds=30),
                ),
                ChannelConnection(
                    tenant_id=tenant_id,
                    provider=ChannelProvider.API.value,
                    name="Draft API",
                    status="draft",
                    configuration_json={},
                ),
                ChannelConnection(
                    tenant_id=tenant_id,
                    provider=ChannelProvider.WIDGET.value,
                    name="Disabled Widget",
                    status="disabled",
                    configuration_json={},
                ),
            ]
        )
        await session.commit()

    async with factory() as session:
        selected = await channel_health_monitor._due_connections(session, now=now)

    assert selected == [(channel.id, tenant_id)]


async def test_due_selection_uses_bounded_backoff_for_transient_failures(channel_case) -> None:
    factory, tenant_id, healthy_channel = channel_case
    now = datetime.now(UTC)
    async with factory() as session:
        healthy = await session.get(ChannelConnection, healthy_channel.id)
        assert healthy is not None
        healthy.status = "healthy"
        healthy.last_health_at = now - timedelta(seconds=30)
        session.add_all(
            [
                ChannelConnection(
                    tenant_id=tenant_id,
                    provider=ChannelProvider.TELEGRAM.value,
                    name="Fast recovery due",
                    status="unhealthy",
                    configuration_json={},
                    last_health_at=now - timedelta(seconds=20),
                    last_failure_at=now - timedelta(seconds=30),
                ),
                ChannelConnection(
                    tenant_id=tenant_id,
                    provider=ChannelProvider.TELEGRAM.value,
                    name="Fast recovery not due",
                    status="unhealthy",
                    configuration_json={},
                    last_health_at=now - timedelta(seconds=5),
                    last_failure_at=now - timedelta(seconds=5),
                ),
                ChannelConnection(
                    tenant_id=tenant_id,
                    provider=ChannelProvider.SLACK.value,
                    name="Medium recovery due",
                    status="degraded",
                    configuration_json={},
                    last_health_at=now - timedelta(seconds=35),
                    last_failure_at=now - timedelta(minutes=2),
                ),
                ChannelConnection(
                    tenant_id=tenant_id,
                    provider=ChannelProvider.TELEGRAM.value,
                    name="Medium recovery not due",
                    status="unhealthy",
                    configuration_json={},
                    last_health_at=now - timedelta(seconds=20),
                    last_failure_at=now - timedelta(minutes=2),
                ),
                ChannelConnection(
                    tenant_id=tenant_id,
                    provider=ChannelProvider.TELEGRAM.value,
                    name="Slow recovery due",
                    status="unhealthy",
                    configuration_json={},
                    last_health_at=now - timedelta(seconds=65),
                    last_failure_at=now - timedelta(minutes=10),
                ),
                ChannelConnection(
                    tenant_id=tenant_id,
                    provider=ChannelProvider.TELEGRAM.value,
                    name="Slow recovery not due",
                    status="unhealthy",
                    configuration_json={},
                    last_health_at=now - timedelta(seconds=45),
                    last_failure_at=now - timedelta(minutes=10),
                ),
            ]
        )
        await session.commit()

    async with factory() as session:
        selected = await channel_health_monitor._due_connections(session, now=now)

    selected_ids = {connection_id for connection_id, _ in selected}
    assert healthy_channel.id not in selected_ids
    assert len(selected_ids) == 3


async def test_run_once_isolates_provider_exception_and_continues_other_channels(
    channel_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, tenant_id, first = channel_case
    async with factory() as session:
        second = ChannelConnection(
            tenant_id=tenant_id,
            provider=ChannelProvider.TELEGRAM.value,
            name="Second Telegram",
            status="configured",
            configuration_json={},
            last_health_at=datetime.now(UTC) - timedelta(minutes=10),
        )
        session.add(second)
        await session.commit()
        await session.refresh(second)
        second_id = second.id

    class MixedConnector:
        async def health_check(self, context: ChannelConnectionContext) -> dict[str, str]:
            if context.connection_id == first.id:
                raise RuntimeError("provider transport exploded")
            return {"status": "healthy"}

    monkeypatch.setattr(channel_health_monitor.channel_registry, "get", lambda _provider: MixedConnector())

    result = await channel_health_monitor.run_once(factory)

    assert result == {"due": 2, "checked": 1, "failed": 1}
    async with factory() as session:
        first_value = await session.get(ChannelConnection, first.id)
        second_value = await session.get(ChannelConnection, second_id)
        assert first_value is not None
        assert second_value is not None
        assert first_value.status == "configured"
        assert second_value.status == "healthy"


def test_channel_health_monitor_is_wired_into_compose_and_kubernetes() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    compose = (repo_root / "compose.yaml").read_text(encoding="utf-8")
    kustomization = (repo_root / "kubernetes" / "base" / "kustomization.yaml").read_text(encoding="utf-8")
    manifest = (repo_root / "kubernetes" / "base" / "channel-health-monitor.yaml").read_text(
        encoding="utf-8"
    )

    assert "  channel-health-monitor:\n" in compose
    assert 'command: ["python", "-m", "northstar_api.workers.channel_health_monitor"]' in compose
    assert "OTEL_SERVICE_NAME: northstar-channel-health-monitor" in compose
    assert "- channel-health-monitor.yaml" in kustomization
    assert "readinessProbe:" in manifest
    assert "livenessProbe:" in manifest
    assert manifest.count("northstar_api.workers.worker_process_probe") == 2
    assert manifest.count("northstar_api.workers.channel_health_monitor") == 3
