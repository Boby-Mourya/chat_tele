from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from northstar_api.database import Base
from northstar_api.lead_crm.models import CRMConnection, CRMWebhookEvent
from northstar_api.lead_crm.workspace_scope import WorkspaceCRMConnection
from northstar_api.models import Role, Tenant, Workspace, WorkspaceRole
from northstar_api.routers.crm_webhook_events import list_crm_webhook_events
from northstar_api.security import Principal


@pytest.fixture
async def webhook_visibility_case() -> AsyncIterator[tuple[AsyncSession, Principal, CRMConnection]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        tenant = Tenant(slug=f"webhook-ops-{uuid4().hex}", name="Webhook operations tenant")
        session.add(tenant)
        await session.flush()
        workspace = Workspace(
            tenant_id=tenant.id,
            name="Primary webhook workspace",
            slug=f"primary-{uuid4().hex[:8]}",
        )
        other_workspace = Workspace(
            tenant_id=tenant.id,
            name="Other webhook workspace",
            slug=f"other-{uuid4().hex[:8]}",
        )
        session.add_all([workspace, other_workspace])
        await session.flush()
        connection = CRMConnection(
            tenant_id=tenant.id,
            provider="salesforce",
            name="Primary Salesforce",
            status="healthy",
            configuration_json={},
        )
        other_connection = CRMConnection(
            tenant_id=tenant.id,
            provider="hubspot",
            name="Other HubSpot",
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
        now = datetime(2026, 9, 12, 11, 0, tzinfo=UTC)
        session.add_all([
            CRMWebhookEvent(
                tenant_id=tenant.id,
                connection_id=connection.id,
                provider="salesforce",
                external_event_id="primary-processed",
                event_type="lead.updated",
                verification_status="verified",
                processing_status="processed",
                payload_hash="a" * 64,
                payload_json={"apiKey": "must-not-be-returned", "email": "private@example.com"},
                correlation_id="corr-processed",
                received_at=now - timedelta(minutes=2),
                processed_at=now - timedelta(minutes=1),
            ),
            CRMWebhookEvent(
                tenant_id=tenant.id,
                connection_id=connection.id,
                provider="salesforce",
                external_event_id="primary-ignored",
                event_type="lead.updated",
                verification_status="verified",
                processing_status="ignored",
                payload_hash="b" * 64,
                payload_json={"token": "also-private"},
                correlation_id="corr-ignored",
                received_at=now,
                processed_at=now,
                last_error="no_effective_changes",
            ),
            CRMWebhookEvent(
                tenant_id=tenant.id,
                connection_id=other_connection.id,
                provider="hubspot",
                external_event_id="other-workspace-event",
                event_type="contact.updated",
                verification_status="verified",
                processing_status="processed",
                payload_hash="c" * 64,
                payload_json={"secret": "other-workspace"},
                correlation_id="corr-other",
                received_at=now + timedelta(minutes=1),
                processed_at=now + timedelta(minutes=1),
            ),
        ])
        await session.commit()
        principal = Principal(
            user_id=uuid4(),
            tenant_id=tenant.id,
            role=Role.MEMBER,
            token_id="webhook-ops-test",
            workspace_id=workspace.id,
            workspace_role=WorkspaceRole.MANAGER,
            permissions=frozenset({"crm.view"}),
        )
        yield session, principal, connection

    await engine.dispose()


async def test_webhook_event_visibility_is_workspace_scoped_and_payload_safe(webhook_visibility_case) -> None:
    session, principal, connection = webhook_visibility_case

    rows = await list_crm_webhook_events(
        principal,
        session,
        connection_id=None,
        processing_status=None,
        limit=100,
    )

    assert [row.correlation_id for row in rows] == ["corr-ignored", "corr-processed"]
    assert all(row.connection_id == connection.id for row in rows)
    assert {row.processing_status for row in rows} == {"processed", "ignored"}
    dumped = rows[0].model_dump()
    assert "payload_json" not in dumped
    assert "payload" not in dumped
    assert "payload_hash" not in dumped
    assert "external_event_id" not in dumped


async def test_webhook_event_visibility_filters_status_and_connection(webhook_visibility_case) -> None:
    session, principal, connection = webhook_visibility_case

    ignored = await list_crm_webhook_events(
        principal,
        session,
        connection_id=connection.id,
        processing_status="ignored",
        limit=20,
    )

    assert len(ignored) == 1
    assert ignored[0].correlation_id == "corr-ignored"
    assert ignored[0].last_error == "no_effective_changes"
    assert ignored[0].event_type == "lead.updated"
