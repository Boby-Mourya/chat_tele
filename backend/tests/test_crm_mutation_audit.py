from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from northstar_api.database import Base
from northstar_api.lead_crm.api_schemas import (
    CRMConnectionCreate,
    CRMMappingPut,
    CRMRouteCreate,
    CRMWorkspaceSettingsPatch,
)
from northstar_api.lead_crm.audit_models import IntegrationAuditEvent
from northstar_api.lead_crm.domain import CRMProvider
from northstar_api.lead_crm.models import CRMConnection, CRMDelivery, IntegrationDeadLetter
from northstar_api.lead_crm.workspace_scope import WorkspaceCRMConnection
from northstar_api.models import Agent, Lead, Role, Tenant, User, Workspace, WorkspaceRole
from northstar_api.routers.crm_dead_letters import replay_crm_dead_letter
from northstar_api.routers.crm_route_admin import CRMRoutePatch, delete_crm_route, patch_crm_route
from northstar_api.routers.crm_scoped import (
    cancel_crm_delivery,
    create_crm_connection,
    create_crm_route,
    delete_crm_connection,
    put_crm_mapping,
    retry_crm_delivery,
)
from northstar_api.routers.crm_workspace_settings import update_crm_workspace_settings
from northstar_api.security import Principal


@pytest.fixture
async def audit_case() -> AsyncIterator[tuple[AsyncSession, Principal, CRMConnection, Lead]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        tenant = Tenant(slug=f"crm-audit-{uuid4().hex}", name="CRM audit tenant")
        user = User(
            email=f"audit-{uuid4().hex}@example.com",
            name="CRM Admin",
            password_hash="test-only",
        )
        session.add_all([tenant, user])
        await session.flush()
        workspace = Workspace(
            tenant_id=tenant.id,
            name="Audit workspace",
            slug=f"audit-{uuid4().hex[:8]}",
            created_by=user.id,
        )
        session.add(workspace)
        await session.flush()
        agent = Agent(tenant_id=tenant.id, workspace_id=workspace.id, name="Audit agent")
        session.add(agent)
        await session.flush()
        lead = Lead(
            tenant_id=tenant.id,
            workspace_id=workspace.id,
            agent_id=agent.id,
            name="Audit lead",
            status="new",
            consent=True,
            fields_json={},
        )
        connection = CRMConnection(
            tenant_id=tenant.id,
            provider="generic_rest",
            name="Existing CRM",
            status="healthy",
            configuration_json={},
        )
        session.add_all([lead, connection])
        await session.flush()
        session.add(
            WorkspaceCRMConnection(
                tenant_id=tenant.id,
                workspace_id=workspace.id,
                connection_id=connection.id,
            )
        )
        await session.commit()
        principal = Principal(
            user_id=user.id,
            tenant_id=tenant.id,
            role=Role.ADMIN,
            token_id="crm-audit-test",
            workspace_id=workspace.id,
            workspace_role=WorkspaceRole.ADMIN,
            permissions=frozenset({"crm.view", "crm.manage", "audit.view"}),
        )
        yield session, principal, connection, lead

    await engine.dispose()


async def _events(session: AsyncSession, tenant_id: UUID) -> list[IntegrationAuditEvent]:
    return list(
        await session.scalars(
            select(IntegrationAuditEvent)
            .where(IntegrationAuditEvent.tenant_id == tenant_id)
            .order_by(IntegrationAuditEvent.created_at, IntegrationAuditEvent.action)
        )
    )


async def test_connection_create_and_disable_are_durably_audited(audit_case) -> None:
    session, principal, _, _ = audit_case
    created = await create_crm_connection(
        CRMConnectionCreate(provider=CRMProvider.GENERIC_REST, name="Created CRM"),
        principal,
        session,
    )
    await delete_crm_connection(created.id, principal, session)

    events = await _events(session, principal.tenant_id)
    created_event = next(event for event in events if event.action == "crm.connection.created")
    disabled_event = next(event for event in events if event.action == "crm.connection.disabled")
    assert created_event.workspace_id == principal.workspace_id
    assert created_event.actor_user_id == principal.user_id
    assert created_event.category == "crm"
    assert created_event.after_json["name"] == "Created CRM"
    assert "credentials" not in created_event.after_json
    assert disabled_event.before_json["status"] == "draft"
    assert disabled_event.after_json == {"status": "disabled", "credentialsConfigured": False}


async def test_mapping_settings_and_routes_share_the_mutation_transaction(audit_case) -> None:
    session, principal, connection, _ = audit_case
    await put_crm_mapping(
        connection.id,
        CRMMappingPut(object_name="Leads", mapping={"First_Name": "name", "apiKey": "do-not-store"}),
        principal,
        session,
    )
    await update_crm_workspace_settings(
        connection.id,
        CRMWorkspaceSettingsPatch(auto_sync_new_leads=False, auto_sync_updates=True),
        principal,
        session,
    )
    route = await create_crm_route(
        CRMRouteCreate(name="Qualified leads", priority=20, connection_ids=[connection.id]),
        principal,
        session,
    )
    await patch_crm_route(
        route.id,
        CRMRoutePatch(priority=10, conditions={"status": "qualified"}),
        principal,
        session,
    )
    await delete_crm_route(route.id, principal, session)

    events = await _events(session, principal.tenant_id)
    actions = {event.action for event in events}
    assert {
        "crm.mapping.updated",
        "crm.workspace_settings.updated",
        "crm.route.created",
        "crm.route.updated",
        "crm.route.deleted",
    }.issubset(actions)
    mapping_event = next(event for event in events if event.action == "crm.mapping.updated")
    assert mapping_event.after_json["mapping"]["apiKey"] == "[REDACTED]"
    settings_event = next(event for event in events if event.action == "crm.workspace_settings.updated")
    assert settings_event.before_json["autoSyncNewLeads"] is True
    assert settings_event.after_json["autoSyncNewLeads"] is False
    route_update = next(event for event in events if event.action == "crm.route.updated")
    assert route_update.before_json["priority"] == 20
    assert route_update.after_json["priority"] == 10


async def test_delivery_recovery_cancel_and_dlq_replay_are_audited(audit_case) -> None:
    session, principal, connection, lead = audit_case
    retry_delivery = CRMDelivery(
        tenant_id=principal.tenant_id,
        lead_id=lead.id,
        connection_id=connection.id,
        provider="generic_rest",
        operation="upsert",
        idempotency_key=f"retry-{uuid4().hex}",
        status="failed",
    )
    cancel_delivery = CRMDelivery(
        tenant_id=principal.tenant_id,
        lead_id=lead.id,
        connection_id=connection.id,
        provider="generic_rest",
        operation="upsert",
        idempotency_key=f"cancel-{uuid4().hex}",
        status="queued",
    )
    replay_delivery = CRMDelivery(
        tenant_id=principal.tenant_id,
        lead_id=lead.id,
        connection_id=connection.id,
        provider="generic_rest",
        operation="upsert",
        idempotency_key=f"replay-{uuid4().hex}",
        status="dead_letter",
    )
    session.add_all([retry_delivery, cancel_delivery, replay_delivery])
    await session.flush()
    dead_letter = IntegrationDeadLetter(
        tenant_id=principal.tenant_id,
        delivery_id=replay_delivery.id,
        status="open",
        reason_code="network_error",
        reason_message="Provider unavailable",
        metadata_json={"token": "must-redact-if-audited"},
    )
    session.add(dead_letter)
    await session.commit()

    await retry_crm_delivery(retry_delivery.id, principal, session)
    await cancel_crm_delivery(cancel_delivery.id, principal, session)
    await replay_crm_dead_letter(dead_letter.id, principal, session)

    events = await _events(session, principal.tenant_id)
    retry_events = [event for event in events if event.action == "crm.delivery.retry_requested"]
    assert len(retry_events) == 2
    assert {event.entity_id for event in retry_events} == {str(retry_delivery.id), str(replay_delivery.id)}
    cancel_event = next(event for event in events if event.action == "crm.delivery.cancelled")
    assert cancel_event.before_json["status"] == "queued"
    assert cancel_event.after_json["status"] == "cancelled"
    replay_event = next(event for event in events if event.action == "crm.dead_letter.replayed")
    assert replay_event.entity_id == str(dead_letter.id)
    assert replay_event.workspace_id == principal.workspace_id
    assert replay_event.after_json["status"] == "resolved"
    await session.refresh(dead_letter)
    assert dead_letter.status == "resolved"
