from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from northstar_api.database import Base
from northstar_api.lead_crm.connectors import CRMConnectionContext, CRMHealthResult
from northstar_api.lead_crm.domain import CRMProvider, IntegrationHealthStatus
from northstar_api.lead_crm.models import CRMConnection, IntegrationHealthSnapshot
from northstar_api.lead_crm.workspace_scope import WorkspaceCRMConnection
from northstar_api.models import Tenant, User, Workspace, WorkspaceMembership, WorkspaceRole
from northstar_api.notifications import Notification
from northstar_api.workers import crm_health_monitor


@pytest.fixture
async def incident_case() -> AsyncIterator[
    tuple[async_sessionmaker[AsyncSession], UUID, UUID, UUID, CRMConnection]
]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        tenant = Tenant(slug=f"health-alert-{uuid4().hex}", name="Health alert tenant")
        admin = User(
            email=f"admin-{uuid4().hex}@example.test",
            name="Workspace Admin",
            password_hash="not-used-by-this-test",  # noqa: S106 - no authentication in this fixture
            is_active=True,
        )
        session.add_all([tenant, admin])
        await session.flush()
        workspace = Workspace(
            tenant_id=tenant.id,
            name="CRM Operations",
            slug=f"crm-ops-{uuid4().hex}",
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
        crm = CRMConnection(
            tenant_id=tenant.id,
            provider=CRMProvider.GENERIC_REST.value,
            name="Primary CRM",
            status="healthy",
            configuration_json={"baseUrl": "https://crm.example.test"},
            last_health_at=datetime.now(UTC) - timedelta(minutes=10),
        )
        session.add(crm)
        await session.flush()
        session.add(
            WorkspaceCRMConnection(
                tenant_id=tenant.id,
                workspace_id=workspace.id,
                connection_id=crm.id,
            )
        )
        await session.commit()
        await session.refresh(crm)
        yield factory, tenant.id, workspace.id, admin.id, crm

    await engine.dispose()


def _install_health_result(
    monkeypatch: pytest.MonkeyPatch,
    *,
    status_box: dict[str, IntegrationHealthStatus],
) -> None:
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

    class Connector:
        async def health_check(self, _context: CRMConnectionContext) -> CRMHealthResult:
            return CRMHealthResult(
                status=status_box["value"],
                checks={
                    "api": "down" if status_box["value"] != IntegrationHealthStatus.HEALTHY else "up",
                    "access_token": "must-not-be-persisted",
                },
                latency_ms=23,
                details={"client_secret": "must-never-enter-notifications"},
            )

    monkeypatch.setattr(crm_health_monitor, "load_connection_context", fake_load)
    monkeypatch.setattr(crm_health_monitor.crm_registry, "get", lambda _provider: Connector())


def test_health_transition_only_alerts_on_incident_boundary_and_recovery() -> None:
    assert crm_health_monitor._health_transition("healthy", "unhealthy") == "incident"
    assert crm_health_monitor._health_transition("connecting", "auth_required") == "incident"
    assert crm_health_monitor._health_transition("unhealthy", "auth_required") is None
    assert crm_health_monitor._health_transition("rate_limited", "degraded") is None
    assert crm_health_monitor._health_transition("auth_required", "healthy") == "recovery"
    assert crm_health_monitor._health_transition("healthy", "healthy") is None


async def test_monitor_notifies_workspace_admin_only_on_incident_and_recovery(
    incident_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, tenant_id, workspace_id, admin_id, crm = incident_case
    status_box = {"value": IntegrationHealthStatus.UNHEALTHY}
    _install_health_result(monkeypatch, status_box=status_box)

    first_check = datetime.now(UTC)
    assert (
        await crm_health_monitor.monitor_connection(
            factory,
            tenant_id=tenant_id,
            connection_id=crm.id,
            now=first_check,
        )
        is True
    )

    status_box["value"] = IntegrationHealthStatus.AUTH_REQUIRED
    assert (
        await crm_health_monitor.monitor_connection(
            factory,
            tenant_id=tenant_id,
            connection_id=crm.id,
            now=first_check + timedelta(minutes=10),
        )
        is True
    )

    status_box["value"] = IntegrationHealthStatus.HEALTHY
    assert (
        await crm_health_monitor.monitor_connection(
            factory,
            tenant_id=tenant_id,
            connection_id=crm.id,
            now=first_check + timedelta(minutes=20),
        )
        is True
    )

    assert (
        await crm_health_monitor.monitor_connection(
            factory,
            tenant_id=tenant_id,
            connection_id=crm.id,
            now=first_check + timedelta(minutes=30),
        )
        is True
    )

    async with factory() as session:
        notifications = list(await session.scalars(select(Notification)))
        assert len(notifications) == 2
        by_title = {value.title: value for value in notifications}
        incident = by_title["CRM connection needs attention"]
        recovery = by_title["CRM connection recovered"]

        assert incident.workspace_id == workspace_id
        assert incident.recipient_user_id == admin_id
        assert incident.category == "crm"
        assert incident.severity == "warning"
        assert incident.action_url == "/integrations"
        assert incident.action_label == "Review CRM health"
        assert incident.metadata_json == {
            "connectionId": str(crm.id),
            "provider": "generic_rest",
            "previousStatus": "healthy",
            "currentStatus": "unhealthy",
            "transition": "incident",
        }
        assert "must-not-be-persisted" not in str(incident.metadata_json)
        assert "must-never-enter-notifications" not in incident.body

        assert recovery.workspace_id == workspace_id
        assert recovery.recipient_user_id == admin_id
        assert recovery.category == "crm"
        assert recovery.severity == "info"
        assert recovery.metadata_json["previousStatus"] == "auth_required"
        assert recovery.metadata_json["currentStatus"] == "healthy"
        assert recovery.metadata_json["transition"] == "recovery"
        assert incident.dedupe_key != recovery.dedupe_key


async def test_unbound_connection_keeps_health_snapshot_without_notification(
    incident_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, tenant_id, _workspace_id, _admin_id, crm = incident_case
    status_box = {"value": IntegrationHealthStatus.UNHEALTHY}
    _install_health_result(monkeypatch, status_box=status_box)

    async with factory() as session:
        await session.execute(
            delete(WorkspaceCRMConnection).where(
                WorkspaceCRMConnection.connection_id == crm.id,
                WorkspaceCRMConnection.tenant_id == tenant_id,
            )
        )
        await session.commit()

    checked_at = datetime.now(UTC)
    assert (
        await crm_health_monitor.monitor_connection(
            factory,
            tenant_id=tenant_id,
            connection_id=crm.id,
            now=checked_at,
        )
        is True
    )

    async with factory() as session:
        refreshed = await session.get(CRMConnection, crm.id)
        assert refreshed is not None
        assert refreshed.status == "unhealthy"
        snapshot = await session.scalar(
            select(IntegrationHealthSnapshot).where(IntegrationHealthSnapshot.connection_id == crm.id)
        )
        assert snapshot is not None
        assert list(await session.scalars(select(Notification))) == []


async def test_notification_failure_does_not_rollback_health_snapshot(
    incident_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, tenant_id, _workspace_id, _admin_id, crm = incident_case
    status_box = {"value": IntegrationHealthStatus.UNHEALTHY}
    _install_health_result(monkeypatch, status_box=status_box)

    async def fail_notification(*_args, **_kwargs) -> int:
        raise RuntimeError("notification store unavailable")

    monkeypatch.setattr(crm_health_monitor, "_notify_health_transition", fail_notification)
    checked_at = datetime.now(UTC)

    assert (
        await crm_health_monitor.monitor_connection(
            factory,
            tenant_id=tenant_id,
            connection_id=crm.id,
            now=checked_at,
        )
        is True
    )

    async with factory() as session:
        refreshed = await session.get(CRMConnection, crm.id)
        assert refreshed is not None
        assert refreshed.status == "unhealthy"
        snapshot = await session.scalar(
            select(IntegrationHealthSnapshot).where(IntegrationHealthSnapshot.connection_id == crm.id)
        )
        assert snapshot is not None
        assert snapshot.status == "unhealthy"
