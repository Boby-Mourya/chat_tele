from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from northstar_api.database import Base
from northstar_api.lead_crm.models import CRMConnection, IntegrationHealthSnapshot
from northstar_api.lead_crm.workspace_scope import WorkspaceCRMConnection
from northstar_api.models import Role, Tenant, Workspace, WorkspaceRole
from northstar_api.routers import crm as legacy_crm
from northstar_api.routers.crm_health_history import list_crm_health_history, run_crm_health_check
from northstar_api.security import Principal


@pytest.fixture
async def health_case() -> AsyncIterator[
    tuple[AsyncSession, Principal, CRMConnection, CRMConnection]
]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        tenant = Tenant(slug=f"health-history-{uuid4().hex}", name="Health history tenant")
        session.add(tenant)
        await session.flush()
        workspace = Workspace(
            tenant_id=tenant.id,
            name="Primary workspace",
            slug=f"primary-{uuid4().hex[:8]}",
        )
        other_workspace = Workspace(
            tenant_id=tenant.id,
            name="Other workspace",
            slug=f"other-{uuid4().hex[:8]}",
        )
        session.add_all([workspace, other_workspace])
        await session.flush()
        connection = CRMConnection(
            tenant_id=tenant.id,
            provider="generic_rest",
            name="Primary CRM",
            status="healthy",
            configuration_json={},
        )
        other_connection = CRMConnection(
            tenant_id=tenant.id,
            provider="generic_rest",
            name="Other CRM",
            status="healthy",
            configuration_json={},
        )
        session.add_all([connection, other_connection])
        await session.flush()
        session.add_all([
            WorkspaceCRMConnection(
                tenant_id=tenant.id,
                workspace_id=workspace.id,
                connection_id=connection.id,
            ),
            WorkspaceCRMConnection(
                tenant_id=tenant.id,
                workspace_id=other_workspace.id,
                connection_id=other_connection.id,
            ),
        ])
        await session.commit()
        principal = Principal(
            user_id=uuid4(),
            tenant_id=tenant.id,
            role=Role.ADMIN,
            token_id="health-history-test",
            workspace_id=workspace.id,
            workspace_role=WorkspaceRole.ADMIN,
            permissions=frozenset({"crm.view", "crm.manage"}),
        )
        yield session, principal, connection, other_connection

    await engine.dispose()


async def test_health_check_persists_only_safe_snapshot_fields(
    health_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, principal, connection, _ = health_case

    async def fake_test_crm_connection(
        connection_id: UUID,
        _principal: Principal,
        _session: AsyncSession,
    ) -> dict[str, object]:
        assert connection_id == connection.id
        return {
            "status": "healthy",
            "checks": {
                "api": "ok",
                "credentials": "configured",
                "access_token": "must-not-be-persisted",
                "oauth_access_token": "prefixed-secret-must-not-be-persisted",
            },
            "latencyMs": 37,
            "details": {"access_token": "also-must-not-be-persisted"},
        }

    monkeypatch.setattr(legacy_crm, "test_crm_connection", fake_test_crm_connection)

    result = await run_crm_health_check(connection.id, principal, session)

    assert result.connection_id == connection.id
    assert result.status == "healthy"
    assert result.latency_ms == 37
    assert result.checks == {
        "api": "ok",
        "credentials": "configured",
        "access_token": "[REDACTED]",
        "oauth_access_token": "[REDACTED]",
    }
    assert set(result.model_dump()) == {
        "id", "connection_id", "status", "checks", "latency_ms", "checked_at",
    }

    stored = list(
        await session.scalars(
            select(IntegrationHealthSnapshot).where(
                IntegrationHealthSnapshot.tenant_id == principal.tenant_id,
                IntegrationHealthSnapshot.connection_id == connection.id,
            )
        )
    )
    assert len(stored) == 1
    assert stored[0].checks_json == result.checks
    assert "details" not in stored[0].checks_json
    assert "must-not-be-persisted" not in str(stored[0].checks_json)


async def test_health_history_is_workspace_scoped(
    health_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, principal, connection, other_connection = health_case

    async def fake_test_crm_connection(
        _connection_id: UUID,
        _principal: Principal,
        _session: AsyncSession,
    ) -> dict[str, object]:
        return {"status": "healthy", "checks": {"api": "ok"}, "latencyMs": 12, "details": {}}

    monkeypatch.setattr(legacy_crm, "test_crm_connection", fake_test_crm_connection)
    await run_crm_health_check(connection.id, principal, session)
    session.add(
        IntegrationHealthSnapshot(
            tenant_id=principal.tenant_id,
            connection_id=other_connection.id,
            status="unhealthy",
            checks_json={"api": "failed"},
            latency_ms=99,
        )
    )
    await session.commit()

    history = await list_crm_health_history(connection.id, principal, session, limit=50)
    assert len(history) == 1
    assert history[0].connection_id == connection.id

    with pytest.raises(HTTPException) as exc_info:
        await list_crm_health_history(other_connection.id, principal, session, limit=50)
    assert exc_info.value.status_code == 404


async def test_handled_connection_failure_is_snapshotted_before_error_is_returned(
    health_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, principal, connection, _ = health_case

    async def fake_failed_test(
        connection_id: UUID,
        _principal: Principal,
        current_session: AsyncSession,
    ) -> dict[str, object]:
        value = await current_session.get(CRMConnection, connection_id)
        assert value is not None
        value.status = "auth_required"
        await current_session.commit()
        raise HTTPException(status_code=409, detail="CRM credentials require reconnection")

    monkeypatch.setattr(legacy_crm, "test_crm_connection", fake_failed_test)

    with pytest.raises(HTTPException) as exc_info:
        await run_crm_health_check(connection.id, principal, session)
    assert exc_info.value.status_code == 409

    snapshots = list(
        await session.scalars(
            select(IntegrationHealthSnapshot).where(
                IntegrationHealthSnapshot.tenant_id == principal.tenant_id,
                IntegrationHealthSnapshot.connection_id == connection.id,
            )
        )
    )
    assert len(snapshots) == 1
    assert snapshots[0].status == "auth_required"
    assert snapshots[0].checks_json == {"credentials": "reconnect_required"}
