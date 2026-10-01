from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.agent_purpose import AgentPurpose, get_agent_purpose
from northstar_api.config import get_settings
from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.education import EducationCourse
from northstar_api.education_batches import EducationBatch
from northstar_api.education_enrollment_events import EducationEnrollmentEvent
from northstar_api.education_enrollments import EducationEnrollment
from northstar_api.education_student_identities import EducationStudentIdentity
from northstar_api.education_student_import_schemas import StudentImportRow
from northstar_api.education_students import EducationStudent
from northstar_api.lead_crm.normalization import normalize_identity
from northstar_api.lead_crm.services import lead_domain_service
from northstar_api.models import Agent, KnowledgeSource, Lead, WhatsAppConnection, Workspace
from northstar_api.routers.education_enrollments import _validate_assignment
from northstar_api.schemas import APIModel
from northstar_api.security import Principal
from northstar_api.services.education_student_import import StudentImportConflictError, commit_student_import
from northstar_api.services.outbox import enqueue_event
from northstar_api.services.student_identity import normalize_student_identity

router = APIRouter(prefix="/education/agents/{agent_id}/enrollment-events", tags=["education"])
DB = Annotated[AsyncSession, Depends(get_session)]
Manager = Annotated[Principal, Depends(require_permissions("education.manage"))]
Viewer = Annotated[Principal, Depends(require_permissions("education.view"))]


@router.get("/readiness")
async def enrollment_readiness(agent_id: UUID, request: Request, principal: Viewer, session: DB):
    from sqlalchemy import func

    from northstar_api.modules.whatsapp.graph import token_expiry_is_current

    agent = await scoped_bot(session, principal, agent_id)
    identities = (
        (
            await session.scalars(
                select(EducationStudentIdentity)
                .join(
                    EducationEnrollment,
                    EducationEnrollment.student_id == EducationStudentIdentity.student_id,
                )
                .where(
                    EducationEnrollment.tenant_id == agent.tenant_id,
                    EducationEnrollment.workspace_id == agent.workspace_id,
                    EducationEnrollment.agent_id == agent.id,
                    EducationEnrollment.status == "active",
                    EducationStudentIdentity.identity_type == "whatsapp",
                    EducationStudentIdentity.status != "revoked",
                )
            )
        )
        .unique()
        .all()
    )
    connection = await session.scalar(
        select(WhatsAppConnection).where(
            WhatsAppConnection.tenant_id == agent.tenant_id,
            WhatsAppConnection.workspace_id == agent.workspace_id,
            WhatsAppConnection.agent_id == agent.id,
        )
    )
    sources = await session.scalar(
        select(func.count(KnowledgeSource.id)).where(
            KnowledgeSource.tenant_id == agent.tenant_id, KnowledgeSource.agent_id == agent.id
        )
    )
    return {
        "endpoint": f"{(get_settings().crm_oauth_public_base_url or str(request.base_url)).rstrip('/')}{get_settings().app_api_prefix}/education/agents/{agent.id}/enrollment-events",
        "whatsappConnected": bool(
            connection
            and connection.status == "connected"
            and token_expiry_is_current(connection.token_expires_at)
        ),
        "verifiedStudentNumbers": sum(item.status == "verified" for item in identities),
        "pendingStudentNumbers": sum(item.status == "pending" for item in identities),
        "knowledgeSources": sources or 0,
        "aiProviderConfigured": bool(get_settings().nvidia_api_key),
    }


class EnrollmentEventPayload(APIModel):
    event_id: str = Field(min_length=1, max_length=160)
    source: str = Field(min_length=1, max_length=60)
    payment_status: Literal["paid"]
    access_granted: Literal[True]
    payment_reference: str = Field(min_length=1, max_length=160)
    consent: bool = False
    row: StudentImportRow

    @field_validator("event_id", "source", "payment_reference")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A non-empty value is required")
        return value.strip()

    @model_validator(mode="after")
    def enrollment_required(self):
        if not self.row.course_code or self.row.enrollment_status != "active":
            raise ValueError("An active Course, Batch and Agent enrollment is required")
        if self.row.identity_type != "whatsapp" or not self.row.identifier:
            raise ValueError("Provide the student's WhatsApp identity, including country code")
        return self


class EnrollmentEventOut(APIModel):
    event_id: str
    source: str
    student_id: UUID
    enrollment_id: UUID
    lead_id: UUID
    duplicate: bool = False
    crm_sync: str = "queued"


async def scoped_bot(session: AsyncSession, principal: Principal, agent_id: UUID) -> Agent:
    agent = await session.scalar(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.tenant_id == principal.tenant_id,
            Agent.workspace_id == principal.workspace_id,
            Agent.deleted_at.is_(None),
        )
    )
    if not agent:
        raise HTTPException(404, "Bot not found in this workspace")
    if (
        await get_agent_purpose(
            session, tenant_id=agent.tenant_id, workspace_id=agent.workspace_id, agent_id=agent.id
        )
        != AgentPurpose.EDUCATION
    ):
        raise HTTPException(422, "Select an Education bot")
    return agent


def receipt_out(receipt: EducationEnrollmentEvent, *, duplicate=False) -> EnrollmentEventOut:
    return EnrollmentEventOut(
        event_id=receipt.event_id,
        source=receipt.source,
        student_id=receipt.student_id,
        enrollment_id=receipt.enrollment_id,
        lead_id=receipt.lead_id,
        duplicate=duplicate,
    )


@router.get("", response_model=list[EnrollmentEventOut])
async def list_events(agent_id: UUID, principal: Viewer, session: DB):
    await scoped_bot(session, principal, agent_id)
    receipts = (
        await session.scalars(
            select(EducationEnrollmentEvent)
            .where(
                EducationEnrollmentEvent.tenant_id == principal.tenant_id,
                EducationEnrollmentEvent.workspace_id == principal.workspace_id,
                EducationEnrollmentEvent.agent_id == agent_id,
            )
            .order_by(EducationEnrollmentEvent.created_at.desc())
            .limit(25)
        )
    ).all()
    return [receipt_out(receipt) for receipt in receipts]


@router.post("", response_model=EnrollmentEventOut)
async def enroll_event(agent_id: UUID, payload: EnrollmentEventPayload, principal: Manager, session: DB):
    agent = await scoped_bot(session, principal, agent_id)
    if payload.row.agent_public_id != agent.public_id:
        raise HTTPException(422, "The row Agent ID must match the bot in this endpoint")
    # Serialize event processing per workspace. The receipt unique constraint is
    # an additional defense against concurrent retries on every database backend.
    await session.scalar(select(Workspace).where(Workspace.id == agent.workspace_id).with_for_update())
    fingerprint = hashlib.sha256(
        json.dumps(payload.model_dump(mode="json"), sort_keys=True).encode()
    ).hexdigest()
    prior = await session.scalar(
        select(EducationEnrollmentEvent).where(
            EducationEnrollmentEvent.workspace_id == agent.workspace_id,
            EducationEnrollmentEvent.tenant_id == agent.tenant_id,
            EducationEnrollmentEvent.agent_id == agent_id,
            EducationEnrollmentEvent.source == payload.source,
            EducationEnrollmentEvent.event_id == payload.event_id,
        )
    )
    if prior:
        if prior.fingerprint != fingerprint:
            raise HTTPException(409, "This event ID was already used with different data")
        return receipt_out(prior, duplicate=True)
    try:
        result = await apply_event(session, agent, payload, fingerprint)
        await session.commit()
        return result
    except (IntegrityError, StudentImportConflictError) as exc:
        await session.rollback()
        raise HTTPException(
            409, "Enrollment data changed concurrently; retry with the same event ID"
        ) from exc


async def apply_event(session: AsyncSession, agent: Agent, payload: EnrollmentEventPayload, fingerprint: str):
    row = payload.row
    tid, wid = agent.tenant_id, agent.workspace_id
    course = await session.scalar(
        select(EducationCourse).where(
            EducationCourse.tenant_id == tid,
            EducationCourse.workspace_id == wid,
            EducationCourse.code == row.course_code,
        )
    )
    batch = await session.scalar(
        select(EducationBatch).where(
            EducationBatch.tenant_id == tid,
            EducationBatch.workspace_id == wid,
            EducationBatch.code == row.batch_code,
        )
    )
    if not course or not batch or batch.course_id != course.id:
        raise HTTPException(422, "Select an existing Course and its Batch in this workspace")
    if course.status != "active" or batch.status != "active":
        raise HTTPException(409, "Activate the Course and Batch before enrolling")
    for value, label in ((row.starts_on, "start"), (row.ends_on, "end")):
        if value and (
            (batch.starts_on and value < batch.starts_on) or (batch.ends_on and value > batch.ends_on)
        ):
            raise HTTPException(422, f"Enrollment {label} must be within the Batch dates")
    try:
        number = normalize_student_identity(row.identity_type, row.identifier)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    student = await session.scalar(
        select(EducationStudent)
        .where(
            EducationStudent.tenant_id == tid,
            EducationStudent.workspace_id == wid,
            EducationStudent.student_number == row.student_number,
        )
        .with_for_update()
    )
    if student is None:
        preview, result = await commit_student_import(session, tenant_id=tid, workspace_id=wid, rows=[row])
        if result is None:
            raise HTTPException(422, "; ".join(preview.rows[0].errors))
        student = await session.scalar(
            select(EducationStudent).where(
                EducationStudent.tenant_id == tid,
                EducationStudent.workspace_id == wid,
                EducationStudent.student_number == row.student_number,
            )
        )
    else:
        if student.status != "active":
            raise HTTPException(409, "Reactivate the Student manually before enrolling")
        identities = (
            await session.scalars(
                select(EducationStudentIdentity).where(
                    EducationStudentIdentity.tenant_id == tid,
                    EducationStudentIdentity.workspace_id == wid,
                    EducationStudentIdentity.student_id == student.id,
                    EducationStudentIdentity.identity_type == "whatsapp",
                )
            )
        ).all()
        identity = next((item for item in identities if item.normalized_identifier == number), None)
        if identity and identity.status == "revoked":
            raise HTTPException(409, "This WhatsApp identity is revoked; review it in Students")
        if not identity:
            if any(item.status != "revoked" for item in identities):
                raise HTTPException(
                    409, "Student has a different WhatsApp number; review the change in Students"
                )
            identity = EducationStudentIdentity(
                tenant_id=tid,
                workspace_id=wid,
                student_id=student.id,
                identity_type="whatsapp",
                identifier=number,
                normalized_identifier=number,
                is_primary=True,
                label=payload.source,
                status="pending",
            )
            session.add(identity)
        if row.identity_verified:
            identity.status = "verified"
            identity.verified_at = identity.verified_at or datetime.now(UTC)
        student.name = row.name
        if row.email:
            student.email = str(row.email)
        student.custom_fields = {**(student.custom_fields or {}), **row.custom_fields}
    assert student is not None
    await _validate_assignment(
        session,
        tenant_id=tid,
        workspace_id=wid,
        student_id=student.id,
        course_id=course.id,
        batch_id=batch.id,
        agent_id=agent.id,
        require_active_domain=True,
    )
    enrollment = await session.scalar(
        select(EducationEnrollment).where(
            EducationEnrollment.tenant_id == tid,
            EducationEnrollment.workspace_id == wid,
            EducationEnrollment.student_id == student.id,
            EducationEnrollment.course_id == course.id,
            EducationEnrollment.batch_id == batch.id,
            EducationEnrollment.agent_id == agent.id,
        )
    )
    if enrollment and enrollment.status not in ("pending", "active"):
        raise HTTPException(
            409, "Existing enrollment is restricted or ended; review it manually before granting access"
        )
    if not enrollment:
        enrollment = EducationEnrollment(
            tenant_id=tid,
            workspace_id=wid,
            student_id=student.id,
            course_id=course.id,
            batch_id=batch.id,
            agent_id=agent.id,
            status="active",
        )
        session.add(enrollment)
    enrollment.status = "active"
    # Missing dates preserve existing access limits; an event cannot silently remove them.
    if row.starts_on is not None:
        enrollment.starts_on = row.starts_on
    if row.ends_on is not None:
        enrollment.ends_on = row.ends_on
    if enrollment.starts_on and enrollment.ends_on and enrollment.starts_on > enrollment.ends_on:
        raise HTTPException(422, "Enrollment end date cannot precede its start")
    await session.flush()
    previous_receipt = await session.scalar(
        select(EducationEnrollmentEvent)
        .where(
            EducationEnrollmentEvent.tenant_id == tid,
            EducationEnrollmentEvent.workspace_id == wid,
            EducationEnrollmentEvent.enrollment_id == enrollment.id,
        )
        .order_by(EducationEnrollmentEvent.created_at.desc())
        .limit(1)
    )
    lead = await session.get(Lead, previous_receipt.lead_id) if previous_receipt else None
    created = lead is None
    if lead is None:
        lead = Lead(
            tenant_id=tid, workspace_id=wid, agent_id=agent.id, status="qualified", consent=payload.consent
        )
        session.add(lead)
    lead.name, lead.email, lead.phone = student.name, student.email, number
    lead.consent = lead.consent or payload.consent
    lead.fields_json = {
        **(lead.fields_json or {}),
        **row.custom_fields,
        "student_id": str(student.id),
        "student_number": student.student_number,
        "enrollment_id": str(enrollment.id),
        "course_code": course.code,
        "batch_code": batch.code,
        "lms_source": payload.source,
        "payment_status": "paid",
        "payment_reference": payload.payment_reference,
        "lms_access_granted": True,
        "enrollment_status": "active",
    }
    await session.flush()
    await session.refresh(lead)
    profile = await lead_domain_service.ensure_profile(
        session,
        lead=lead,
        source_channel="api",
        source_provider=payload.source,
        source_external_id=student.student_number,
    )
    profile.custom_fields_json = dict(lead.fields_json)
    profile.qualification_reason = (
        f"Paid enrollment; LMS access granted. Student: {student.student_number}. "
        f"Course: {course.code}. Batch: {batch.code}. Bot: {agent.name}. "
        f"Payment: {payload.payment_reference}. Source: {payload.source}. "
        f"Enrollment: {enrollment.id}."
    )[:1000]
    parts = (lead.name or "").split(None, 1)
    profile.first_name = parts[0][:100] if parts else None
    profile.last_name = parts[1][:100] if len(parts) > 1 else None
    normalized = normalize_identity(lead.email, lead.phone)
    profile.normalized_email, profile.normalized_phone = normalized.email, normalized.phone
    profile.consent_status = "granted" if lead.consent else "unknown"
    event_data = {
        "leadId": str(lead.id),
        "workspaceId": str(wid),
        "agentId": str(agent.id),
        "sourceChannel": "api",
    }
    if created:
        for event_type in ("lead.captured.v1", "lead.created.v1"):
            enqueue_event(
                session,
                tenant_id=tid,
                aggregate_type="lead",
                aggregate_id=lead.id,
                event_type=event_type,
                payload=event_data,
            )
    enqueue_event(
        session,
        tenant_id=tid,
        aggregate_type="lead",
        aggregate_id=lead.id,
        event_type="lead.crm.sync.requested.v1",
        payload={**event_data, "reason": "lead_created" if created else "education_payment_enrollment"},
    )
    enqueue_event(
        session,
        tenant_id=tid,
        aggregate_type="education_enrollment",
        aggregate_id=enrollment.id,
        event_type="education.enrollment.automated.v1",
        payload={
            "workspaceId": str(wid),
            "agentId": str(agent.id),
            "studentId": str(student.id),
            "enrollmentId": str(enrollment.id),
            "source": payload.source,
            "eventId": payload.event_id,
        },
    )
    receipt = EducationEnrollmentEvent(
        tenant_id=tid,
        workspace_id=wid,
        agent_id=agent.id,
        source=payload.source,
        event_id=payload.event_id,
        fingerprint=fingerprint,
        student_id=student.id,
        enrollment_id=enrollment.id,
        lead_id=lead.id,
    )
    session.add(receipt)
    await session.flush()
    return receipt_out(receipt)
