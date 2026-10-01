from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from northstar_api.database import Base
from northstar_api.lead_crm.channel_models import ChannelConnection, ChannelHealthSnapshot
from northstar_api.lead_crm.channel_scope import WorkspaceChannelConnection
from northstar_api.lead_crm.channels import ChannelConnectionContext
from northstar_api.lead_crm.domain import ChannelProvider
from northstar_api.models import Role, Tenant, Workspace, WorkspaceRole
from northstar_api.routers import channels
from northstar_api.security import Principal


@pytest.fixture
async def manual_health_case() -> AsyncIterator[
    tuple[AsyncSession, Principal, ChannelConnection, ChannelConnection]
]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        tenant = Tenant(slug=f"manual-channel-health-{uuid4().hex}", name="Manual health")
        session.add(tenant)
        await session.flush()

        workspace = Workspace(
            tenant_id=tenant.id,
            name="Primary workspace",
            slug=f"manual-primary-{uuid4().hex[:8]}",
        )
        other_workspace = Workspace(
            tenant_id=tenant.id,
            name="Other workspace",
            slug=f"manual-other-{uuid4().hex[:8]}",
        )
        session.add_all([workspace, other_workspace])
        await session.flush()

        connection = ChannelConnection(
            tenant_id=tenant.id,
            provider=ChannelProvider.TELEGRAM.value,
            name="Primary Telegram",
            status="configured",
            configuration_json={},
        )
        other_connection = ChannelConnection(
            tenant_id=tenant.id,
            provider=ChannelProvider.SLACK.value,
            name="Other Slack",
            status="configured",
            configuration_json={},
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
            token_id="manual-channel-health",
            workspace_id=workspace.id,
            workspace_role=WorkspaceRole.ADMIN,
            permissions=frozenset({"integrations.view", "integrations.manage"}),
        )
        yield session, principal, connection, other_connection

    await engine.dispose()


def _utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def test_channel_credentials_can_be_corrected_without_changing_webhook_or_leaking_secrets(
    manual_health_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from northstar_api.lead_crm.credentials import credential_store

    monkeypatch.setenv("CRM_CREDENTIAL_ENCRYPTION_KEY", "test-channel-update-key")
    session, principal, connection, other = manual_health_case
    original_public_id = connection.public_id
    payload = channels.ChannelConnectionCreate(
        provider=ChannelProvider.TELEGRAM,
        name="Ignored replacement name",
        credentials={"bot_token": "corrected-secret", "webhook_secret": "verification-secret"},
    )
    result = await channels.update_channel_connection(connection.id, payload, principal, session)
    assert result.id == connection.id
    assert result.public_id == original_public_id
    assert result.name == "Primary Telegram"
    assert result.status == "configured"
    assert "corrected-secret" not in result.model_dump_json()
    assert b"corrected-secret" not in connection.credentials_encrypted
    assert credential_store.decrypt(connection.credentials_encrypted)["bot_token"] == payload.credentials["bot_token"]
    with pytest.raises(HTTPException) as error:
        await channels.update_channel_connection(other.id, payload, principal, session)
    assert error.value.status_code == 404
    wrong_provider = channels.ChannelConnectionCreate(
        provider=ChannelProvider.SLACK, name="Slack", credentials={"bot_token": "value"}
    )
    with pytest.raises(HTTPException) as error:
        await channels.update_channel_connection(connection.id, wrong_provider, principal, session)
    assert error.value.status_code == 422


async def test_manual_channel_health_check_persists_safe_snapshot(
    manual_health_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, principal, connection, _ = manual_health_case

    class HealthyConnector:
        async def health_check(self, context: ChannelConnectionContext) -> dict[str, str]:
            assert context.connection_id == connection.id
            return {
                "status": "healthy",
                "username": "provider-detail-must-not-be-snapshotted",
                "access_token": "secret-token-must-not-be-snapshotted",
            }

    monkeypatch.setattr(channels.channel_registry, "get", lambda _provider: HealthyConnector())

    result = await channels.test_channel_connection(connection.id, principal, session)

    assert result["status"] == "healthy"
    assert result["username"] == "provider-detail-must-not-be-snapshotted"
    stored = await session.get(ChannelConnection, connection.id)
    assert stored is not None
    assert stored.status == "healthy"
    assert stored.last_health_at is not None
    assert stored.last_error is None

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
    assert _utc(snapshot.checked_at) == _utc(stored.last_health_at)
    rendered = str(snapshot.__dict__)
    assert "provider-detail-must-not-be-snapshotted" not in rendered
    assert "secret-token-must-not-be-snapshotted" not in rendered


async def test_manual_nonhealthy_result_is_recorded_without_provider_details(
    manual_health_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, principal, connection, _ = manual_health_case

    class AuthRequiredConnector:
        async def health_check(self, _context: ChannelConnectionContext) -> dict[str, str]:
            return {
                "status": "auth_required",
                "provider_error": "raw provider body must not be persisted",
                "token": "provider-secret-must-not-be-persisted",
            }

    monkeypatch.setattr(channels.channel_registry, "get", lambda _provider: AuthRequiredConnector())

    result = await channels.test_channel_connection(connection.id, principal, session)

    assert result["status"] == "auth_required"
    stored = await session.get(ChannelConnection, connection.id)
    assert stored is not None
    assert stored.status == "auth_required"
    assert stored.last_error == "Channel health validation failed"

    snapshot = await session.scalar(
        select(ChannelHealthSnapshot).where(ChannelHealthSnapshot.connection_id == connection.id)
    )
    assert snapshot is not None
    assert snapshot.status == "auth_required"
    assert snapshot.error_code is None
    rendered = str(snapshot.__dict__)
    assert "raw provider body" not in rendered
    assert "provider-secret" not in rendered


async def test_manual_channel_health_check_cannot_cross_workspace_scope(
    manual_health_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, principal, _, other_connection = manual_health_case

    class ConnectorThatMustNotRun:
        async def health_check(self, _context: ChannelConnectionContext) -> dict[str, str]:
            raise AssertionError("cross-workspace connector must not run")

    monkeypatch.setattr(channels.channel_registry, "get", lambda _provider: ConnectorThatMustNotRun())

    with pytest.raises(HTTPException) as exc_info:
        await channels.test_channel_connection(other_connection.id, principal, session)
    assert exc_info.value.status_code == 404

    leaked_snapshot = await session.scalar(
        select(ChannelHealthSnapshot).where(ChannelHealthSnapshot.connection_id == other_connection.id)
    )
    assert leaked_snapshot is None
