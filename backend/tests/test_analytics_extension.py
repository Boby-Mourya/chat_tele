from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from httpx import AsyncClient

from northstar_api.agent_purpose import AgentPurpose, AgentPurposeSetting
from northstar_api.database import SessionFactory
from northstar_api.education import EducationCourse
from northstar_api.education_batches import EducationBatch
from northstar_api.education_conversation_context import EducationConversationContext
from northstar_api.education_enrollments import EducationEnrollment, EnrollmentStatus
from northstar_api.education_student_activity import EducationStudentActivityEvent
from northstar_api.education_students import EducationStudent
from northstar_api.lead_crm.domain import (
    CRMDeliveryStatus,
    CRMProvider,
    LeadLifecycleStatus,
    QualificationStatus,
)
from northstar_api.lead_crm.models import CRMConnection, CRMDelivery, LeadProfile
from northstar_api.models import Agent, Channel, Conversation, Lead, Workspace


async def _scope(client: AsyncClient, auth_headers: dict[str, str]) -> tuple[UUID, UUID, UUID]:
    workspace = await client.get("/api/v1/workspace", headers=auth_headers)
    assert workspace.status_code == 200, workspace.text
    agent_response = await client.get("/api/v1/agents", headers=auth_headers)
    assert agent_response.status_code == 200, agent_response.text
    agents = agent_response.json()
    assert agents
    return (
        UUID(workspace.json()["tenantId"]),
        UUID(workspace.json()["id"]),
        UUID(agents[0]["id"]),
    )


async def test_analytics_supports_real_period_selection_and_domain_metrics(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    tenant_id, workspace_id, agent_id = await _scope(client, auth_headers)
    suffix = uuid4().hex[:8]

    async with SessionFactory() as session:
        lead = Lead(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            name=f"Analytics Lead {suffix}",
            status=LeadLifecycleStatus.CONVERTED.value,
            consent=True,
            fields_json={},
        )
        session.add(lead)
        await session.flush()
        session.add(
            LeadProfile(
                tenant_id=tenant_id,
                lead_id=lead.id,
                lifecycle_status=LeadLifecycleStatus.CONVERTED.value,
                qualification_status=QualificationStatus.QUALIFIED.value,
                qualification_score=95,
            )
        )
        connection = CRMConnection(
            tenant_id=tenant_id,
            provider=CRMProvider.ZOHO.value,
            name=f"Analytics CRM {suffix}",
        )
        session.add(connection)
        await session.flush()
        session.add(
            CRMDelivery(
                tenant_id=tenant_id,
                lead_id=lead.id,
                connection_id=connection.id,
                provider=CRMProvider.ZOHO.value,
                idempotency_key=f"analytics:{suffix}",
                status=CRMDeliveryStatus.VERIFIED.value,
                verification_status="verified",
            )
        )

        course = EducationCourse(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            code=f"AN-{suffix}",
            name=f"Analytics Course {suffix}",
        )
        session.add(course)
        await session.flush()
        batch = EducationBatch(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            course_id=course.id,
            code=f"B-{suffix}",
            name=f"Analytics Batch {suffix}",
        )
        student = EducationStudent(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            student_number=f"ST-{suffix}",
            name=f"Analytics Student {suffix}",
        )
        session.add_all([batch, student])
        await session.flush()
        enrollment = EducationEnrollment(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            student_id=student.id,
            course_id=course.id,
            batch_id=batch.id,
            agent_id=agent_id,
            status=EnrollmentStatus.ACTIVE.value,
        )
        session.add(enrollment)
        await session.flush()
        conversation = Conversation(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            visitor_id=f"analytics-{suffix}",
            visitor_name="Analytics Student",
            channel=Channel.WIDGET,
        )
        session.add(conversation)
        await session.flush()
        session.add(
            EducationConversationContext(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                conversation_id=conversation.id,
                agent_id=agent_id,
                student_id=student.id,
                enrollment_id=enrollment.id,
                course_id=course.id,
                batch_id=batch.id,
            )
        )
        session.add(
            EducationStudentActivityEvent(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                student_id=student.id,
                enrollment_id=enrollment.id,
                course_id=course.id,
                batch_id=batch.id,
                agent_id=agent_id,
                conversation_id=conversation.id,
                event_type="analytics.test.activity",
                resolved_at=datetime.now(UTC),
            )
        )
        await session.commit()

    response = await client.get("/api/v1/analytics/summary?days=7", headers=auth_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["period"] == "Last 7 days"
    assert payload["leads"]["created"] >= 1
    assert payload["leads"]["qualified"] >= 1
    assert payload["leads"]["converted"] >= 1
    assert payload["crm"]["deliveries"] >= 1
    assert payload["crm"]["verified"] >= 1
    assert payload["education"]["students"] >= 1
    assert payload["education"]["activeEnrollments"] >= 1
    assert payload["education"]["conversations"] >= 1
    assert payload["education"]["activityEvents"] >= 1
    assert payload["agents"]["total"] >= payload["agents"]["active"]

    ninety = await client.get("/api/v1/analytics/summary?days=90", headers=auth_headers)
    assert ninety.status_code == 200, ninety.text
    assert ninety.json()["period"] == "Last 90 days"

    invalid = await client.get("/api/v1/analytics/summary?days=14", headers=auth_headers)
    assert invalid.status_code == 422, invalid.text


async def test_analytics_excludes_other_workspace_data(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    tenant_id, _, _ = await _scope(client, auth_headers)
    before = await client.get("/api/v1/analytics/summary?days=30", headers=auth_headers)
    assert before.status_code == 200, before.text
    baseline = before.json()
    suffix = uuid4().hex[:8]

    async with SessionFactory() as session:
        other = Workspace(
            tenant_id=tenant_id,
            name=f"Analytics Outside {suffix}",
            slug=f"analytics-outside-{suffix}",
        )
        session.add(other)
        await session.flush()
        outside_agent = Agent(
            tenant_id=tenant_id,
            workspace_id=other.id,
            name=f"Outside Agent {suffix}",
        )
        session.add(outside_agent)
        await session.flush()
        session.add(
            Conversation(
                tenant_id=tenant_id,
                workspace_id=other.id,
                agent_id=outside_agent.id,
                visitor_id=f"outside-{suffix}",
                channel=Channel.WIDGET,
            )
        )
        session.add(
            Lead(
                tenant_id=tenant_id,
                workspace_id=other.id,
                agent_id=outside_agent.id,
                name="Outside Lead",
                status="new",
                consent=False,
                fields_json={},
            )
        )
        await session.commit()

    after = await client.get("/api/v1/analytics/summary?days=30", headers=auth_headers)
    assert after.status_code == 200, after.text
    payload = after.json()
    assert payload["conversations"] == baseline["conversations"]
    assert payload["leads"]["created"] == baseline["leads"]["created"]
    assert payload["agents"]["total"] == baseline["agents"]["total"]


async def test_analytics_does_not_count_soft_deleted_agent_purpose_rows(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    tenant_id, workspace_id, _ = await _scope(client, auth_headers)
    before = await client.get("/api/v1/analytics/summary?days=30", headers=auth_headers)
    assert before.status_code == 200, before.text
    baseline = before.json()["agents"]
    suffix = uuid4().hex[:8]

    async with SessionFactory() as session:
        deleted_agent = Agent(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            name=f"Deleted Analytics Agent {suffix}",
            deleted_at=datetime.now(UTC),
        )
        session.add(deleted_agent)
        await session.flush()
        session.add(
            AgentPurposeSetting(
                agent_id=deleted_agent.id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                purpose=AgentPurpose.EDUCATION.value,
            )
        )
        await session.commit()

    after = await client.get("/api/v1/analytics/summary?days=30", headers=auth_headers)
    assert after.status_code == 200, after.text
    agents = after.json()["agents"]
    assert agents["total"] == baseline["total"]
    assert agents["active"] == baseline["active"]
    assert agents["education"] == baseline["education"]
    assert agents["support"] == baseline["support"]
