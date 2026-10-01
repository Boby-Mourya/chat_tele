from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from northstar_api.database import Base
from northstar_api.lead_crm.channel_models import ChannelConnection, ChannelHealthSnapshot
from northstar_api.lead_crm.channel_scope import WorkspaceChannelConnection
from northstar_api.lead_crm.channels import ChannelConnectionContext
from northstar_api.lead_crm.credentials import CredentialStoreError
from northstar_api.lead_crm.domain import ChannelProvider
from northstar_api.models import Role, Tenant, Workspace, WorkspaceRole
from northstar_api.routers import api_router
from northstar_api.routers.channel_health_history import list_channel_health_history
from northstar_api.security import Principal
from northstar_api.workers import channel_health_monitor


@pytest.fixture
async def history_case() -> AsyncIterator[
    tuple[
        async_sessionmaker[AsyncSession],
        Principal,
        ChannelConnection,
        ChannelConnection,
    ]
]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        tenant = Tenant(slug=f"channel-history-{uuid4().hex}", name="Channel history tenant")
        session.add(tenant)
        await session.flush()
        workspace = Workspace(
            tenant_id=tenant.id,
            name="Primary workspace",
            slug=f"channel-primary-{uuid4().hex[:8]}",
        )
        other_workspace = Workspace(
            tenant_id=tenant.id,
            name="Other workspace",
            slug=f"channel-other-{uuid4().hex[:8]}",
        )
        session.add_all([workspace, other_workspace])
        await session.flush()
        connection = ChannelConnection(
            tenant_id=tenant.id,
            provider=ChannelProvider.TELEGRAM.value,
            name="Primary Telegram",
            status="configured",
            configuration_json={"webhookMode": "managed"},
            last_health_at=datetime.now(UTC) - timedelta(minutes=10),
        )
        other_connection = ChannelConnection(
            tenant_id=tenant.id,
            provider=ChannelProvider.SLACK.value,
            name="Other Slack",
            status="healthy",
            configuration_json={},
            last_health_at=datetime.now(UTC) - timedelta(minutes=10),
        )
        session.add_all([connection, other_connection])
        await session.flush()
        session.add_all(
            [
                WorkspaceChannelConnection(
                    tenant_id=tenant.id,
                    workspace_id=workspace.id,
                    agent_id=None,
                    connection_id=connection.id,
                ),
                WorkspaceChannelConnection(
                    tenant_id=tenant.id,
                    workspace_id=other_workspace.id,
                    agent_id=None,
                    connection_id=other_connection.id,
                ),
            ]
        )
        await session.commit()

        principal = Principal(
            user_id=uuid4(),
            tenant_id=tenant.id,
            role=Role.ADMIN,
            token_id="channel-health-history-test",
            workspace_id=workspace.id,
            workspace_role=WorkspaceRole.ADMIN,
            permissions=frozenset({"integrations.view", "integrations.manage"}),
        )
        yield factory, principal, connection, other_connection

    await engine.dispose()


async def test_scheduled_monitor_persists_safe_channel_health_snapshot(
    history_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, principal, connection, _ = history_case
    checked_at = datetime(2026, 9, 12, 18, 30, tzinfo=UTC)

    class HealthyConnector:
        async def health_check(self, context: ChannelConnectionContext) -> dict[str, str]:
            assert context.connection_id == connection.id
            return {
                "status": "healthy",
                "username": "must-not-be-persisted",
                "access_token": "must-not-be-persisted",
                "provider_error": "must-not-be-persisted",
            }

    monkeypatch.setattr(
        channel_health_monitor.channel_registry,
        "get",
        lambda _provider: HealthyConnector(),
    )

    assert await channel_health_monitor.monitor_connection(
        factory,
        tenant_id=principal.tenant_id,
        connection_id=connection.id,
        now=checked_at,
    ) is True

    async with factory() as session:
        snapshots = list(
            await session.scalars(
                select(ChannelHealthSnapshot).where(
                    ChannelHealthSnapshot.tenant_id == principal.tenant_id,
                    ChannelHealthSnapshot.connection_id == connection.id,
                )
            )
        )
        assert len(snapshots) == 1
        snapshot = snapshots[0]
        assert snapshot.status == "healthy"
        assert snapshot.error_code is None
        value = snapshot.checked_at
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        assert value == checked_at
        assert "must-not-be-persisted" not in str(snapshot.__dict__)

        history = await list_channel_health_history(connection.id, principal, session, limit=50)
        assert len(history) == 1
        assert history[0].model_dump().keys() == {
            "id",
            "connection_id",
            "status",
            "error_code",
            "checked_at",
        }
        assert "must-not-be-persisted" not in str(history[0].model_dump())


async def test_credential_failure_snapshot_uses_normalized_error_code_only(
    history_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, principal, connection, _ = history_case
    checked_at = datetime(2026, 9, 12, 18, 40, tzinfo=UTC)

    async with factory() as session:
        stored = await session.get(ChannelConnection, connection.id)
        assert stored is not None
        stored.credentials_encrypted = b"unreadable"
        await session.commit()

    def fail_decrypt(_value: bytes) -> dict[str, object]:
        raise CredentialStoreError("token secret provider-body must not be persisted")

    monkeypatch.setattr(channel_health_monitor.credential_store, "decrypt", fail_decrypt)

    assert await channel_health_monitor.monitor_connection(
        factory,
        tenant_id=principal.tenant_id,
        connection_id=connection.id,
        now=checked_at,
    ) is True

    async with factory() as session:
        snapshot = await session.scalar(
            select(ChannelHealthSnapshot).where(
                ChannelHealthSnapshot.tenant_id == principal.tenant_id,
                ChannelHealthSnapshot.connection_id == connection.id,
            )
        )
        assert snapshot is not None
        assert snapshot.status == "auth_required"
        assert snapshot.error_code == "credential_error"
        assert "token" not in str(snapshot.__dict__)
        assert "secret" not in str(snapshot.__dict__)
        assert "provider-body" not in str(snapshot.__dict__)


async def test_channel_health_history_is_workspace_scoped_ordered_and_limited(history_case) -> None:
    factory, principal, connection, other_connection = history_case
    first = datetime(2026, 9, 12, 17, 0, tzinfo=UTC)
    second = datetime(2026, 9, 12, 17, 5, tzinfo=UTC)

    async with factory() as session:
        session.add_all(
            [
                ChannelHealthSnapshot(
                    tenant_id=principal.tenant_id,
                    connection_id=connection.id,
                    status="unhealthy",
                    error_code=None,
                    checked_at=first,
                ),
                ChannelHealthSnapshot(
                    tenant_id=principal.tenant_id,
                    connection_id=connection.id,
                    status="healthy",
                    error_code=None,
                    checked_at=second,
                ),
                ChannelHealthSnapshot(
                    tenant_id=principal.tenant_id,
                    connection_id=other_connection.id,
                    status="configuration_error",
                    error_code="configuration_error",
                    checked_at=second,
                ),
            ]
        )
        await session.commit()

        latest = await list_channel_health_history(connection.id, principal, session, limit=1)
        assert len(latest) == 1
        assert latest[0].connection_id == connection.id
        assert latest[0].status == "healthy"

        with pytest.raises(HTTPException) as exc_info:
            await list_channel_health_history(other_connection.id, principal, session, limit=50)
        assert exc_info.value.status_code == 404


async def test_channel_health_history_requires_active_workspace_scope(history_case) -> None:
    factory, principal, connection, _ = history_case
    no_workspace = Principal(
        user_id=principal.user_id,
        tenant_id=principal.tenant_id,
        role=principal.role,
        token_id="channel-health-history-no-workspace",
        workspace_id=None,
        workspace_role=None,
        permissions=principal.permissions,
    )

    async with factory() as session:
        with pytest.raises(HTTPException) as exc_info:
            await list_channel_health_history(connection.id, no_workspace, session, limit=50)
    assert exc_info.value.status_code == 404


def test_channel_health_history_route_is_registered_before_generic_channel_routes() -> None:
    paths = [route.path for route in api_router.routes]
    history_path = "/channels/connections/{connection_id}/health-history"
    generic_path = "/channels/connections/{connection_id}"

    assert history_path in paths
    assert generic_path in paths
    assert paths.index(history_path) < paths.index(generic_path)
