from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from northstar_api.database import Base
from northstar_api.lead_crm.connectors import CRMConnectionContext, CRMError, CRMHealthResult
from northstar_api.lead_crm.domain import CRMProvider, IntegrationHealthStatus, NormalizedCRMErrorCode
from northstar_api.lead_crm.models import CRMConnection, IntegrationHealthSnapshot
from northstar_api.models import Tenant
from northstar_api.workers import crm_health_monitor


@pytest.fixture
async def monitor_case() -> AsyncIterator[tuple[async_sessionmaker[AsyncSession], UUID, CRMConnection]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        tenant = Tenant(slug=f"health-monitor-{uuid4().hex}", name="Health monitor tenant")
        session.add(tenant)
        await session.flush()
        crm = CRMConnection(
            tenant_id=tenant.id,
            provider=CRMProvider.GENERIC_REST.value,
            name="Monitored CRM",
            status="healthy",
            configuration_json={"baseUrl": "https://crm.example.test"},
            last_health_at=datetime.now(UTC) - timedelta(minutes=10),
        )
        session.add(crm)
        await session.commit()
        await session.refresh(crm)
        yield factory, tenant.id, crm

    await engine.dispose()


async def test_due_health_check_persists_safe_snapshot_and_updates_connection(
    monitor_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, tenant_id, crm = monitor_case
    checked_at = datetime.now(UTC)

    async def fake_load(
        session: AsyncSession,
        *,
        tenant_id: UUID,
        connection_id: UUID,
    ) -> tuple[CRMConnection, CRMConnectionContext]:
        connection = await session.get(CRMConnection, connection_id)
        assert connection is not None
        return connection, CRMConnectionContext(
            tenant_id=tenant_id,
            connection_id=connection_id,
            provider=CRMProvider.GENERIC_REST,
            configuration={},
            credentials={},
        )

    class HealthyConnector:
        async def health_check(self, _context: CRMConnectionContext) -> CRMHealthResult:
            return CRMHealthResult(
                status=IntegrationHealthStatus.HEALTHY,
                checks={
                    "api": "up",
                    "credentials": "up",
                    "oauth_access_token": "must-not-be-persisted",
                },
                latency_ms=19,
                details={"access_token": "also-not-persisted"},
            )

    monkeypatch.setattr(crm_health_monitor, "load_connection_context", fake_load)
    monkeypatch.setattr(crm_health_monitor.crm_registry, "get", lambda _provider: HealthyConnector())

    recorded = await crm_health_monitor.monitor_connection(
        factory,
        tenant_id=tenant_id,
        connection_id=crm.id,
        now=checked_at,
    )

    assert recorded is True
    async with factory() as session:
        refreshed = await session.get(CRMConnection, crm.id)
        assert refreshed is not None
        assert refreshed.status == "healthy"
        assert refreshed.last_error is None
        assert refreshed.last_health_at is not None
        refreshed_health_at = refreshed.last_health_at
        if refreshed_health_at.tzinfo is None:
            refreshed_health_at = refreshed_health_at.replace(tzinfo=UTC)
        assert refreshed_health_at == checked_at
        snapshots = list(
            await session.scalars(
                select(IntegrationHealthSnapshot).where(
                    IntegrationHealthSnapshot.tenant_id == tenant_id,
                    IntegrationHealthSnapshot.connection_id == crm.id,
                )
            )
        )
        assert len(snapshots) == 1
        assert snapshots[0].status == "healthy"
        assert snapshots[0].latency_ms == 19
        assert snapshots[0].checks_json == {
            "api": "up",
            "credentials": "up",
            "oauth_access_token": "[REDACTED]",
        }
        assert "must-not-be-persisted" not in str(snapshots[0].checks_json)
        assert "details" not in snapshots[0].checks_json


async def test_recent_connection_is_not_checked_twice_in_same_interval(
    monitor_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, tenant_id, crm = monitor_case
    now = datetime.now(UTC)
    async with factory() as session:
        value = await session.get(CRMConnection, crm.id)
        assert value is not None
        value.last_health_at = now - timedelta(seconds=30)
        await session.commit()

    called = False

    async def unexpected_load(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("recent connection should not be checked")

    monkeypatch.setattr(crm_health_monitor, "load_connection_context", unexpected_load)
    recorded = await crm_health_monitor.monitor_connection(
        factory,
        tenant_id=tenant_id,
        connection_id=crm.id,
        now=now,
    )

    assert recorded is False
    assert called is False
    async with factory() as session:
        snapshots = list(await session.scalars(select(IntegrationHealthSnapshot)))
        assert snapshots == []


async def test_authentication_failure_records_safe_auth_required_snapshot(
    monitor_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, tenant_id, crm = monitor_case
    checked_at = datetime.now(UTC)

    async def failed_load(*_args, **_kwargs):
        raise CRMError(
            NormalizedCRMErrorCode.AUTHENTICATION_ERROR,
            "provider response contained sensitive credential details",
            requires_reconnect=True,
        )

    monkeypatch.setattr(crm_health_monitor, "load_connection_context", failed_load)
    recorded = await crm_health_monitor.monitor_connection(
        factory,
        tenant_id=tenant_id,
        connection_id=crm.id,
        now=checked_at,
    )

    assert recorded is True
    async with factory() as session:
        refreshed = await session.get(CRMConnection, crm.id)
        assert refreshed is not None
        assert refreshed.status == "auth_required"
        assert refreshed.last_error == "Scheduled health check failed: authentication_error"
        assert "sensitive" not in refreshed.last_error
        snapshot = await session.scalar(
            select(IntegrationHealthSnapshot).where(IntegrationHealthSnapshot.connection_id == crm.id)
        )
        assert snapshot is not None
        assert snapshot.status == "auth_required"
        assert snapshot.checks_json == {
            "healthCheck": "failed",
            "errorCode": "authentication_error",
        }


async def test_due_selection_excludes_recent_draft_and_disabled_connections(
    monitor_case,
) -> None:
    factory, tenant_id, crm = monitor_case
    now = datetime.now(UTC)
    async with factory() as session:
        due = await session.get(CRMConnection, crm.id)
        assert due is not None
        due.last_health_at = now - timedelta(minutes=10)
        session.add_all(
            [
                CRMConnection(
                    tenant_id=tenant_id,
                    provider="generic_rest",
                    name="Recent CRM",
                    status="healthy",
                    configuration_json={},
                    last_health_at=now - timedelta(seconds=30),
                ),
                CRMConnection(
                    tenant_id=tenant_id,
                    provider="generic_rest",
                    name="Draft CRM",
                    status="draft",
                    configuration_json={},
                ),
                CRMConnection(
                    tenant_id=tenant_id,
                    provider="generic_rest",
                    name="Disabled CRM",
                    status="disabled",
                    configuration_json={},
                ),
            ]
        )
        await session.commit()

    async with factory() as session:
        selected = await crm_health_monitor._due_connections(session, now=now)

    assert selected == [(crm.id, tenant_id)]


def test_health_monitor_is_wired_into_compose_and_kubernetes() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    compose = (repo_root / "compose.yaml").read_text(encoding="utf-8")
    kustomization = (repo_root / "kubernetes" / "base" / "kustomization.yaml").read_text(encoding="utf-8")

    assert "  crm-health-monitor:\n" in compose
    assert 'command: ["python", "-m", "northstar_api.workers.crm_health_monitor"]' in compose
    assert "OTEL_SERVICE_NAME: northstar-crm-health-monitor" in compose
    assert "- crm-health-monitor.yaml" in kustomization
