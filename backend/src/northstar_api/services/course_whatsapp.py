"""WhatsApp enrollment selection and last-moment reply authorization.

This module never publishes documents or starts ingestion. A durable receipt
makes a numeric menu reply safe to retry after a provider/network failure.
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import select

from northstar_api.course_knowledge_dispatch import CourseStudyReceipt
from northstar_api.course_knowledge_models import CourseEnrollmentAccess, CourseStudySelection
from northstar_api.education_conversation_context import EducationConversationContext
from northstar_api.education_student_identities import StudentIdentityType
from northstar_api.models import BotWorkflow, Message, MessageRole
from northstar_api.modules.whatsapp.accounts import connection_client
from northstar_api.modules.whatsapp.graph import split_whatsapp_text
from northstar_api.services.course_knowledge_policy import KnowledgePolicyError, fingerprint
from northstar_api.services.course_study_access import authorize_study_access
from northstar_api.services.education_runtime_authorization import (
    EducationAccessReason,
    EducationIdentityCandidate,
    authorize_education_access,
)
from northstar_api.services.student_identity import find_workspace_student_identity

DENIAL = "Your course access is not active for this WhatsApp number. Please contact your institute to verify your number and enrollment."


async def _daily_menu_welcome(session, agent, identity) -> str | None:
    """Return the configured welcome only when it has not been sent today."""
    workflow = await session.scalar(select(BotWorkflow).where(
        BotWorkflow.tenant_id == agent.tenant_id,
        BotWorkflow.workspace_id == agent.workspace_id,
        BotWorkflow.agent_id == agent.id,
        BotWorkflow.status == "active",
    ))
    if workflow is None:
        return None
    step = next((item for item in workflow.steps_json or [] if (
        (item.get("config") or {}).get("systemAction") == "education_daily_welcome"
        and item.get("enabled", True)
    )), None)
    if step is None:
        return None
    zone = ZoneInfo(str(step.get("calendarTimezone") or "Asia/Kolkata"))
    local_today = datetime.now(UTC).astimezone(zone).date()
    start = datetime.combine(local_today, time.min, tzinfo=zone).astimezone(UTC)
    menu_receipts = (await session.scalars(select(CourseStudyReceipt).where(
        CourseStudyReceipt.tenant_id == agent.tenant_id,
        CourseStudyReceipt.workspace_id == agent.workspace_id,
        CourseStudyReceipt.agent_id == agent.id,
        CourseStudyReceipt.identity_id == identity.id,
        CourseStudyReceipt.created_at >= start,
    ))).all()
    if any((item.prompt or "").startswith(str(step.get("message") or "")) for item in menu_receipts):
        return None
    replies = (await session.scalars(
        select(Message)
        .join(EducationConversationContext, EducationConversationContext.conversation_id == Message.conversation_id)
        .where(
            EducationConversationContext.tenant_id == agent.tenant_id,
            EducationConversationContext.workspace_id == agent.workspace_id,
            EducationConversationContext.agent_id == agent.id,
            EducationConversationContext.student_id == identity.student_id,
            Message.role == MessageRole.ASSISTANT,
            Message.created_at >= start,
        )
    )).all()
    if any(str((item.content_json or {}).get("workflowStepId") or "") == str(step.get("id")) for item in replies):
        return None
    return str(step.get("message") or "").strip() or None


async def _verified_identity(session, agent, sender):
    return await find_workspace_student_identity(
        session,
        tenant_id=agent.tenant_id,
        workspace_id=agent.workspace_id,
        identity_type=StudentIdentityType.WHATSAPP,
        identifier="+" + sender.lstrip("+"),
        verified_only=True,
    )


async def _selection_epoch(session, agent, identity):
    from northstar_api.education import EducationCourse
    from northstar_api.education_batches import EducationBatch
    from northstar_api.education_enrollments import EducationEnrollment

    if identity is None:
        return fingerprint({"identity": None})
    rows = (
        await session.execute(
            select(
                EducationEnrollment.id,
                EducationEnrollment.updated_at,
                EducationBatch.updated_at,
                EducationCourse.updated_at,
                CourseEnrollmentAccess.revision,
                CourseEnrollmentAccess.active,
                CourseEnrollmentAccess.selected_paper_id,
            )
            .join(EducationBatch, EducationBatch.id == EducationEnrollment.batch_id)
            .join(EducationCourse, EducationCourse.id == EducationEnrollment.course_id)
            .outerjoin(CourseEnrollmentAccess, CourseEnrollmentAccess.enrollment_id == EducationEnrollment.id)
            .where(
                EducationEnrollment.tenant_id == agent.tenant_id,
                EducationEnrollment.workspace_id == agent.workspace_id,
                EducationEnrollment.agent_id == agent.id,
                EducationEnrollment.student_id == identity.student_id,
            )
            .order_by(EducationEnrollment.id)
        )
    ).all()
    state = await session.scalar(
        select(CourseStudySelection).where(
            CourseStudySelection.tenant_id == agent.tenant_id,
            CourseStudySelection.workspace_id == agent.workspace_id,
            CourseStudySelection.agent_id == agent.id,
            CourseStudySelection.identity_id == identity.id,
        )
    )
    # Include the current workspace day so date-only access expiration invalidates
    # menu labels even when no administrator modified the enrollment row.
    from northstar_api.services.workspace_dates import workspace_today

    day = await workspace_today(session, tenant_id=agent.tenant_id, workspace_id=agent.workspace_id)
    return fingerprint(
        {
            "identity": str(identity.id),
            "day": str(day),
            "enrollments": [[str(value) for value in row] for row in rows],
            "selection": str(state.enrollment_id) if state else None,
            "menu": state.menu_ids if state else [],
            "menu_open": state.menu_open if state else False,
        }
    )


async def authorize_whatsapp_study(session, *, agent, receipt, connection):
    """Return (access decision, menu handled); caller owns the tutoring flow."""
    from northstar_api.services.outbox import enqueue_event

    identity = EducationIdentityCandidate(
        StudentIdentityType.WHATSAPP, "+" + receipt.sender_wa_id.lstrip("+")
    )
    cached = await session.scalar(
        select(CourseStudyReceipt)
        .where(
            CourseStudyReceipt.receipt_id == receipt.id,
            CourseStudyReceipt.tenant_id == agent.tenant_id,
            CourseStudyReceipt.workspace_id == agent.workspace_id,
            CourseStudyReceipt.agent_id == agent.id,
        )
        .with_for_update()
    )
    if cached:
        # Never replay private enrollment labels after verification was revoked.
        check = await authorize_education_access(
            session,
            tenant_id=agent.tenant_id,
            workspace_id=agent.workspace_id,
            agent=agent,
            identity=identity,
        )
        verified = await _verified_identity(session, agent, receipt.sender_wa_id)
        permitted = (
            verified is not None
            and verified.id == cached.identity_id
            and (check.authorized or check.reason is EducationAccessReason.ENROLLMENT_AMBIGUOUS)
        )
        if not permitted:
            cached.prompt = DENIAL
            # Do not send a new denial after a partial menu delivery; just stop.
            if cached.sent_ids:
                receipt.status = "rejected"
                receipt.last_error = "Education identity or enrollment changed during menu delivery"
                await session.commit()
                return check, True
        if permitted and cached.scope_fingerprint != await _selection_epoch(session, agent, verified):
            cached.prompt = (
                "Your course selection or access changed. Send 'courses' to refresh your current choices."
            )
            if cached.sent_ids:
                receipt.status = "processed"
                await session.commit()
                return check, True
        decision, prompt = check, cached.prompt
    else:
        decision, prompt = await authorize_study_access(
            session,
            tenant_id=agent.tenant_id,
            workspace_id=agent.workspace_id,
            agent=agent,
            identity=identity,
            message=receipt.message_text,
        )
        if decision.authorized and not prompt:
            selection = await session.scalar(
                select(CourseStudySelection)
                .where(
                    CourseStudySelection.tenant_id == agent.tenant_id,
                    CourseStudySelection.workspace_id == agent.workspace_id,
                    CourseStudySelection.agent_id == agent.id,
                    CourseStudySelection.identity_id == decision.identity_id,
                )
                .with_for_update()
            )
            if selection and selection.pending_question:
                receipt.message_text = selection.pending_question
                selection.pending_question = None
        enqueue_event(
            session,
            tenant_id=agent.tenant_id,
            aggregate_type="agent",
            aggregate_id=agent.id,
            event_type="education.access.authorized.v1"
            if decision.authorized
            else "education.access.denied.v1",
            payload={
                **decision.event_payload(),
                "provider": "whatsapp",
                "receiptId": str(receipt.id),
                "selectionRequired": bool(prompt),
            },
        )
        if not prompt and decision.authorized:
            return decision, False
        prompt = prompt or DENIAL
        await session.flush()
        verified = await _verified_identity(session, agent, receipt.sender_wa_id)
        daily_welcome = await _daily_menu_welcome(session, agent, verified) if verified else None
        if daily_welcome:
            prompt = f"{daily_welcome}\n\n{prompt}"
        selection_epoch = await _selection_epoch(session, agent, verified)
        cached = CourseStudyReceipt(
            tenant_id=agent.tenant_id,
            workspace_id=agent.workspace_id,
            agent_id=agent.id,
            receipt_id=receipt.id,
            identity_id=decision.identity_id,
            prompt=prompt,
            sent_ids=[],
            scope_fingerprint=selection_epoch,
        )
        session.add(cached)
    await session.commit()  # Menu state/receipt must survive a failed provider send.
    provider, token = await connection_client(session, connection)
    chunks = split_whatsapp_text(prompt)
    sent_ids = list(cached.sent_ids)
    for chunk in chunks[len(sent_ids) :]:
        message_id = await provider.send_text(
            token, phone_number_id=connection.phone_number_id, to=receipt.sender_wa_id, text=chunk
        )
        sent_ids.append(message_id)
        cached.sent_ids = list(sent_ids)
        receipt.outbound_message_ids = list(sent_ids)
        receipt.outbound_message_id = message_id
        await session.commit()
    receipt.status = "rejected" if prompt == DENIAL else "processed"
    receipt.processed_at = datetime.now(UTC)
    receipt.last_error = "Education access: " + decision.reason.value if prompt == DENIAL else None
    await session.commit()
    return decision, True


async def validate_whatsapp_study_reply(session, *, agent, receipt, prepared):
    from northstar_api.course_knowledge_models import CourseResponseContext
    from northstar_api.education_enrollments import EducationEnrollment
    from northstar_api.services.course_knowledge_chat import validate_course_reply

    identity = await _verified_identity(session, agent, receipt.sender_wa_id)
    context = await session.scalar(
        select(CourseResponseContext).where(
            CourseResponseContext.message_id == prepared.assistant_message_id,
            CourseResponseContext.tenant_id == agent.tenant_id,
            CourseResponseContext.workspace_id == agent.workspace_id,
            CourseResponseContext.agent_id == agent.id,
        )
    )
    if identity is None or context is None:
        raise KnowledgePolicyError("Student verification is no longer valid")
    enrollment = await session.scalar(
        select(EducationEnrollment).where(
            EducationEnrollment.id == context.enrollment_id,
            EducationEnrollment.tenant_id == agent.tenant_id,
            EducationEnrollment.workspace_id == agent.workspace_id,
            EducationEnrollment.agent_id == agent.id,
            EducationEnrollment.student_id == identity.student_id,
            EducationEnrollment.status == "active",
        )
    )
    if enrollment is None:
        raise KnowledgePolicyError("The reply no longer belongs to an active enrollment for this number")
    await validate_course_reply(session, prepared, agent)
