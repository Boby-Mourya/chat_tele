from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from northstar_api.database import SessionFactory
from northstar_api.lead_crm.domain import CRMDeliveryStatus
from northstar_api.lead_crm.models import (
    CRMConnection,
    CRMDelivery,
    CRMFieldMapping,
    CRMRoute,
    LeadProfile,
)
from northstar_api.lead_crm.workspace_scope import WorkspaceCRMConnection, WorkspaceCRMRoute
from northstar_api.models import (
    Channel,
    Conversation,
    ConversationState,
    Lead,
    TenantMembership,
    User,
    Workspace,
    WorkspaceMembership,
    WorkspaceRole,
)

pytestmark = pytest.mark.usefixtures("crm_test_plan")

async def _isolated_workspace() -> tuple[uuid.UUID, uuid.UUID]:
    suffix = uuid.uuid4().hex[:10]
    async with SessionFactory() as session:
        user = await session.scalar(select(User).where(User.email == "owner@example.com"))
        assert user is not None
        tenant_membership = await session.scalar(
            select(TenantMembership).where(TenantMembership.user_id == user.id)
        )
        assert tenant_membership is not None
        workspace = Workspace(
            tenant_id=tenant_membership.tenant_id,
            name=f"CRM Workflow {suffix}",
            slug=f"crm-workflow-{suffix}",
            created_by=user.id,
        )
        session.add(workspace)
        await session.flush()
        session.add(
            WorkspaceMembership(
                tenant_id=tenant_membership.tenant_id,
                workspace_id=workspace.id,
                user_id=user.id,
                role=WorkspaceRole.ADMIN,
                all_agents_access=True,
            )
        )
        await session.commit()
        return tenant_membership.tenant_id, workspace.id


async def test_crm_workflow_reports_blockers_for_an_unconfigured_workspace(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    _, workspace_id = await _isolated_workspace()
    headers = {**auth_headers, "X-Workspace-ID": str(workspace_id)}

    response = await client.get("/api/v1/crm/workflow", headers=headers)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["workspaceId"] == str(workspace_id)
    assert payload["readiness"]["ready"] is False
    assert payload["counts"]["localLeads"] == 0
    assert payload["counts"]["totalDeliveries"] == 0
    assert payload["connections"] == []
    stages = {item["id"]: item for item in payload["readiness"]["stages"]}
    assert stages["lead_generation"]["status"] == "blocked"
    assert stages["crm_connection"]["status"] == "blocked"
    assert stages["field_mapping"]["status"] == "blocked"
    assert stages["routing"]["status"] == "blocked"


async def test_crm_workflow_exposes_the_verified_lead_to_crm_journey_without_secrets(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    tenant_id, workspace_id = await _isolated_workspace()
    headers = {**auth_headers, "X-Workspace-ID": str(workspace_id)}
    created_agent = await client.post(
        "/api/v1/agents",
        headers=headers,
        json={
            "name": "CRM Workflow Lead Agent",
            "description": "End-to-end workflow acceptance fixture",
            "purpose": "lead_generation",
            "deploymentChannel": "website",
        },
    )
    assert created_agent.status_code == 201, created_agent.text
    agent_id = uuid.UUID(created_agent.json()["id"])
    now = datetime.now(UTC)

    async with SessionFactory() as session:
        conversation = Conversation(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            visitor_id="workflow-visitor",
            visitor_name="Workflow Lead",
            visitor_email="workflow.lead@example.com",
            channel=Channel.WIDGET,
            state=ConversationState.RESOLVED,
            ended_at=now,
            resolution="qualified",
        )
        session.add(conversation)
        await session.flush()

        lead = Lead(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            conversation_id=conversation.id,
            name="Workflow Lead",
            email="workflow.lead@example.com",
            status="qualified",
            consent=True,
            fields_json={"requirement": "CRM workflow validation"},
        )
        session.add(lead)
        await session.flush()
        session.add(
            LeadProfile(
                tenant_id=tenant_id,
                lead_id=lead.id,
                lifecycle_status="qualified",
                qualification_status="qualified",
                qualification_score=88,
                source_channel="widget",
                source_provider="widget",
            )
        )

        connection = CRMConnection(
            tenant_id=tenant_id,
            provider="zoho",
            name=f"Zoho Workflow {uuid.uuid4().hex[:8]}",
            environment="sandbox",
            status="healthy",
            credentials_encrypted=b"configured-for-test",
            last_health_at=now,
            last_success_at=now,
        )
        session.add(connection)
        await session.flush()
        session.add(
            WorkspaceCRMConnection(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                connection_id=connection.id,
                auto_sync_new_leads=True,
                auto_sync_updates=True,
            )
        )
        session.add(
            CRMFieldMapping(
                tenant_id=tenant_id,
                connection_id=connection.id,
                object_name="Leads",
                version=3,
                status="active",
                mapping_json={
                    "email": {"target": "Email"},
                    "name": {"target": "Full_Name"},
                },
            )
        )
        route = CRMRoute(
            tenant_id=tenant_id,
            name=f"All workflow leads {uuid.uuid4().hex[:8]}",
            enabled=True,
            priority=10,
            conditions_json={},
            actions_json={"connectionIds": [str(connection.id)]},
        )
        session.add(route)
        await session.flush()
        session.add(
            WorkspaceCRMRoute(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                route_id=route.id,
            )
        )
        delivery = CRMDelivery(
            tenant_id=tenant_id,
            lead_id=lead.id,
            connection_id=connection.id,
            provider="zoho",
            operation="upsert",
            idempotency_key=f"workflow:{uuid.uuid4().hex}",
            status=CRMDeliveryStatus.VERIFIED.value,
            attempt_count=1,
            verification_status="verified",
            verification_attempt_count=1,
            external_record_id="zoho-record-1001",
            queued_at=now,
            sent_at=now,
            acknowledged_at=now,
            verified_at=now,
            payload_json={"Email": "workflow.lead@example.com"},
        )
        session.add(delivery)
        await session.commit()

    response = await client.get("/api/v1/crm/workflow?limit=10", headers=headers)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["readiness"]["ready"] is True
    assert payload["counts"]["resolvedConversations"] == 1
    assert payload["counts"]["localLeads"] == 1
    assert payload["counts"]["verifiedDeliveries"] == 1
    assert payload["counts"]["byStatus"]["verified"] == 1
    assert payload["connections"][0]["provider"] == "zoho"
    assert payload["connections"][0]["ready"] is True
    assert payload["connections"][0]["mappingVersion"] == 3
    assert payload["connections"][0]["enabledRouteCount"] == 1

    journey = payload["recentJourneys"][0]
    assert journey["leadId"] == str(lead.id)
    assert journey["conversationId"] == str(conversation.id)
    assert journey["stage"] == "verified"
    assert journey["delivery"]["externalRecordId"] == "zoho-record-1001"
    assert journey["delivery"]["acknowledgedAt"]
    assert journey["delivery"]["verifiedAt"]

    serialized = response.text
    assert "credentialsEncrypted" not in serialized
    assert "payloadJson" not in serialized
    assert "idempotencyKey" not in serialized
