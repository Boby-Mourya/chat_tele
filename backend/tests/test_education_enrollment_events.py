import copy
import uuid

import pytest
from sqlalchemy import func, select

from northstar_api.database import SessionFactory
from northstar_api.education_enrollments import EducationEnrollment
from northstar_api.education_student_identities import StudentIdentityType
from northstar_api.education_students import EducationStudent
from northstar_api.lead_crm.mapping import build_mapped_payload
from northstar_api.lead_crm.models import CRMConnection, CRMRoute, LeadProfile
from northstar_api.lead_crm.workspace_routing import workspace_crm_route_service
from northstar_api.lead_crm.workspace_scope import WorkspaceCRMConnection, WorkspaceCRMRoute
from northstar_api.models import Agent, Lead, OutboxEvent
from northstar_api.services.education_runtime_authorization import (
    EducationIdentityCandidate,
    authorize_education_access,
)

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("crm_test_plan")]


@pytest.fixture
async def domain(client, auth_headers):
    seed = uuid.uuid4().hex[:8].upper()
    course = await client.post(
        "/api/v1/education/courses", headers=auth_headers, json={"code": seed, "name": "API Course"}
    )
    assert course.status_code == 201, course.text
    batch = await client.post(
        "/api/v1/education/batches",
        headers=auth_headers,
        json={
            "courseId": course.json()["id"],
            "code": seed,
            "name": "API Batch",
            "startsOn": "2026-01-01",
            "endsOn": "2027-12-31",
        },
    )
    assert batch.status_code == 201, batch.text
    agent = await client.post(
        "/api/v1/agents",
        headers=auth_headers,
        json={
            "name": f"API Bot {seed}",
            "description": "Education API test",
            "purpose": "education",
            "deploymentChannel": "website",
        },
    )
    assert agent.status_code == 201, agent.text
    assert agent.json()["status"] == "draft"
    body = {
        "eventId": f"paid-{seed}",
        "source": "test-lms",
        "paymentStatus": "paid",
        "accessGranted": True,
        "paymentReference": f"order-{seed}",
        "row": {
            "studentNumber": seed,
            "name": "Enrolled Student",
            "email": f"{seed}@example.com",
            "identityType": "whatsapp",
            "identifier": f"+9191{uuid.uuid4().int % 100_000_000:08d}",
            "identityVerified": True,
            "courseCode": seed,
            "batchCode": seed,
            "agentPublicId": agent.json()["publicId"],
            "enrollmentStatus": "active",
            "startsOn": "2026-01-01",
            "endsOn": "2027-12-31",
        },
    }
    return agent.json(), body, f"/api/v1/education/agents/{agent.json()['id']}/enrollment-events"


async def test_paid_event_provisions_draft_bot_then_activation_and_idempotent_crm(
    client, auth_headers, domain
):
    agent, body, url = domain
    blocked = await client.patch(
        f"/api/v1/agents/{agent['id']}", headers=auth_headers, json={"status": "active"}
    )
    assert blocked.status_code == 409
    # Authenticate the automated integration using the same server key customers use.
    key = await client.post(
        "/api/v1/workspace/api-keys", headers=auth_headers, json={"name": "Enrollment test"}
    )
    assert key.status_code == 201, key.text
    service_headers = {"Authorization": f"Bearer {key.json()['secret']}"}
    response = await client.post(url, headers=service_headers, json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["crmSync"] == "queued"
    assert result["duplicate"] is False
    retry = await client.post(url, headers=service_headers, json=body)
    assert retry.status_code == 200, retry.text
    assert retry.json() == {**result, "duplicate": True}
    changed = copy.deepcopy(body)
    changed["row"]["name"] = "Different Student"
    conflict = await client.post(url, headers=service_headers, json=changed)
    assert conflict.status_code == 409
    active = await client.patch(
        f"/api/v1/agents/{agent['id']}", headers=auth_headers, json={"status": "active"}
    )
    assert active.status_code == 200, active.text
    readiness = await client.get(url + "/readiness", headers=service_headers)
    assert readiness.status_code == 200, readiness.text
    assert readiness.json()["verifiedStudentNumbers"] == 1
    assert readiness.json()["knowledgeSources"] == 0
    assert readiness.json()["endpoint"].endswith(url.removeprefix("/api/v1"))
    async with SessionFactory() as session:
        bot = await session.get(Agent, uuid.UUID(agent["id"]))
        decision = await authorize_education_access(
            session,
            tenant_id=bot.tenant_id,
            workspace_id=bot.workspace_id,
            agent=bot,
            identity=EducationIdentityCandidate(StudentIdentityType.WHATSAPP, body["row"]["identifier"]),
        )
        assert decision.authorized is True
    draft = await client.patch(
        f"/api/v1/agents/{agent['id']}", headers=auth_headers, json={"status": "draft"}
    )
    assert draft.status_code == 200
    async with SessionFactory() as session:
        student = await session.get(EducationStudent, uuid.UUID(result["studentId"]))
        enrollment = await session.get(EducationEnrollment, uuid.UUID(result["enrollmentId"]))
        lead = await session.get(Lead, uuid.UUID(result["leadId"]))
        assert student.student_number == body["row"]["studentNumber"]
        assert enrollment.status == "active"  # Draft does not delete access assignments.
        assert lead.phone == body["row"]["identifier"]
        assert lead.fields_json["payment_status"] == "paid"
        assert lead.fields_json["course_code"] == body["row"]["courseCode"]
        count = await session.scalar(
            select(func.count(OutboxEvent.id)).where(
                OutboxEvent.aggregate_id == str(lead.id),
                OutboxEvent.event_type == "lead.crm.sync.requested.v1",
            )
        )
        assert count == 1
        event = await session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.aggregate_id == str(lead.id),
                OutboxEvent.event_type == "lead.crm.sync.requested.v1",
            )
        )
        assert event.payload["reason"] == "lead_created"
        connection = CRMConnection(
            tenant_id=lead.tenant_id, name=f"Enrollment CRM {lead.id}", provider="zoho", status="healthy"
        )
        route = CRMRoute(
            tenant_id=lead.tenant_id,
            name=f"Enrollment route {lead.id}",
            enabled=True,
            conditions_json={"agentId": str(lead.agent_id)},
        )
        session.add_all([connection, route])
        await session.flush()
        route.actions_json = {"connectionIds": [str(connection.id)]}
        session.add_all(
            [
                WorkspaceCRMConnection(
                    tenant_id=lead.tenant_id,
                    workspace_id=lead.workspace_id,
                    connection_id=connection.id,
                    auto_sync_new_leads=True,
                    auto_sync_updates=False,
                ),
                WorkspaceCRMRoute(
                    tenant_id=lead.tenant_id, workspace_id=lead.workspace_id, route_id=route.id
                ),
            ]
        )
        await session.flush()
        deliveries = await workspace_crm_route_service.create_deliveries(
            session, tenant_id=lead.tenant_id, lead_id=lead.id, sync_reason=event.payload["reason"]
        )
        assert len(deliveries) == 1
        profile = await session.scalar(select(LeadProfile).where(LeadProfile.lead_id == lead.id))
        mapped = build_mapped_payload(
            lead,
            profile,
            {
                "fields": [
                    {"source": "qualificationReason", "target": "Description"},
                    {"source": "phone", "target": "Mobile"},
                ]
            },
            provider="zoho",
        )
        assert body["paymentReference"] in mapped["Description"]
        assert body["row"]["courseCode"] in mapped["Description"]
        assert mapped["Mobile"] == body["row"]["identifier"]
    # New event for the same student and assignment updates its existing lead.
    changed["eventId"] += "-second"
    update = await client.post(url, headers=service_headers, json=changed)
    assert update.status_code == 200, update.text
    assert update.json()["studentId"] == result["studentId"]
    assert update.json()["enrollmentId"] == result["enrollmentId"]
    assert update.json()["leadId"] == result["leadId"]
    history = await client.get(url, headers=auth_headers)
    assert history.status_code == 200
    assert len(history.json()) == 2


async def test_event_rejects_unpaid_unauthorized_mismatched_and_restricted_access(
    client, auth_headers, domain
):
    agent, body, url = domain
    unauth = await client.post(url, json=body)
    assert unauth.status_code == 401
    for patch in ({"paymentStatus": "pending"}, {"accessGranted": False}):
        invalid = await client.post(url, headers=auth_headers, json={**body, **patch})
        assert invalid.status_code == 422
    wrong = copy.deepcopy(body)
    wrong["row"]["agentPublicId"] = "some-other-bot"
    assert (await client.post(url, headers=auth_headers, json=wrong)).status_code == 422
    unknown = await client.post(url.replace(agent["id"], str(uuid.uuid4())), headers=auth_headers, json=body)
    assert unknown.status_code == 404
    created = await client.post(url, headers=auth_headers, json=body)
    assert created.status_code == 200, created.text
    suspended = await client.patch(
        f"/api/v1/education/enrollments/{created.json()['enrollmentId']}",
        headers=auth_headers,
        json={"status": "suspended"},
    )
    assert suspended.status_code == 200
    body["eventId"] += "-new"
    restricted = await client.post(url, headers=auth_headers, json=body)
    assert restricted.status_code == 409
    assert "restricted" in restricted.text


async def test_bulk_import_supports_draft_provisioning_and_rejects_invalid_rows_atomically(
    client, auth_headers, domain
):
    agent, body, _ = domain
    rows = [body["row"]]
    preview = await client.post(
        "/api/v1/education/students/import/preview", headers=auth_headers, json={"rows": rows}
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["invalidRows"] == 0
    assert any("draft" in warning for warning in preview.json()["rows"][0]["warnings"])
    bad = copy.deepcopy(rows[0])
    bad["studentNumber"] += "-INVALID"
    bad["batchCode"] = "NONEXISTENT"
    invalid = await client.post(
        "/api/v1/education/students/import/commit", headers=auth_headers, json={"rows": rows + [bad]}
    )
    assert invalid.status_code == 200
    assert invalid.json()["committed"] is False
    committed = await client.post(
        "/api/v1/education/students/import/commit", headers=auth_headers, json={"rows": rows}
    )
    assert committed.status_code == 200, committed.text
    assert committed.json()["result"]["createdEnrollments"] == 1
    activated = await client.patch(
        f"/api/v1/agents/{agent['id']}", headers=auth_headers, json={"status": "active"}
    )
    assert activated.status_code == 200, activated.text


async def test_pending_identity_stays_blocked_and_whatsapp_activation_requires_connection(
    client, auth_headers, domain
):
    agent, body, url = domain
    body["row"]["identityVerified"] = False
    created = await client.post(url, headers=auth_headers, json=body)
    assert created.status_code == 200, created.text
    async with SessionFactory() as session:
        bot = await session.get(Agent, uuid.UUID(agent["id"]))
        bot.appearance = {**bot.appearance, "deploymentChannel": "whatsapp"}
        await session.commit()
        decision = await authorize_education_access(
            session,
            tenant_id=bot.tenant_id,
            workspace_id=bot.workspace_id,
            agent=bot,
            identity=EducationIdentityCandidate(StudentIdentityType.WHATSAPP, body["row"]["identifier"]),
        )
        assert decision.authorized is False
    blocked = await client.patch(
        f"/api/v1/agents/{agent['id']}", headers=auth_headers, json={"status": "active"}
    )
    assert blocked.status_code == 409
    assert "WhatsApp" in blocked.text
    readiness = await client.get(url + "/readiness", headers=auth_headers)
    assert readiness.json()["pendingStudentNumbers"] == 1
    assert readiness.json()["verifiedStudentNumbers"] == 0
    body["eventId"] += "-verified"
    body["row"]["identityVerified"] = True
    verified = await client.post(url, headers=auth_headers, json=body)
    assert verified.status_code == 200, verified.text
    readiness = await client.get(url + "/readiness", headers=auth_headers)
    assert readiness.json()["verifiedStudentNumbers"] == 1
