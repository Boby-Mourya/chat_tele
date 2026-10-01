"""Bind Telegram accounts only after an authenticated self-contact share."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.education_student_identities import EducationStudentIdentity, StudentIdentityType
from northstar_api.education_students import EducationStudent
from northstar_api.lead_crm.channels import CanonicalInboundEvent
from northstar_api.models import Agent
from northstar_api.services.student_identity import normalize_student_identity

CONTACT_KEYBOARD = {
    "keyboard": [[{"text": "Share my phone number", "request_contact": True}]],
    "resize_keyboard": True,
    "one_time_keyboard": True,
}
PROMPT = "To verify your enrollment, tap Share my phone number below. Use the Telegram account registered with your school."
DENIED = "We could not verify this account. Share your own contact using the button below, or ask your school to check your registered Telegram phone number."


async def telegram_enrollment_notice(
    session: AsyncSession, *, event: CanonicalInboundEvent, agent: Agent
) -> tuple[str, dict[str, Any]] | None:
    if event.metadata.get("chatType") != "private":
        return None
    sender = event.sender.external_id
    if not sender or event.conversation_reference != sender:
        return None
    try:
        sender = normalize_student_identity(StudentIdentityType.TELEGRAM, sender)
    except ValueError:
        return None
    identity = await session.scalar(
        select(EducationStudentIdentity).where(
            EducationStudentIdentity.tenant_id == agent.tenant_id,
            EducationStudentIdentity.workspace_id == agent.workspace_id,
            EducationStudentIdentity.identity_type == "telegram",
            EducationStudentIdentity.normalized_identifier == sender,
        )
    )
    if identity and identity.status == "revoked":
        return DENIED, CONTACT_KEYBOARD
    contact = event.metadata.get("contact")
    if not contact:
        if identity and identity.status == "verified":
            return None
        return PROMPT, CONTACT_KEYBOARD
    if (
        not isinstance(contact, dict)
        or event.metadata.get("forwarded")
        or str(contact.get("user_id")) != sender
    ):
        return DENIED, CONTACT_KEYBOARD
    try:
        raw_phone = str(contact.get("phone_number") or "").strip()
        phone = normalize_student_identity(
            StudentIdentityType.ALTERNATE_PHONE, raw_phone if raw_phone.startswith("+") else "+" + raw_phone
        )
    except ValueError:
        return DENIED, CONTACT_KEYBOARD
    student = await session.scalar(
        select(EducationStudent)
        .where(
            EducationStudent.tenant_id == agent.tenant_id,
            EducationStudent.workspace_id == agent.workspace_id,
            EducationStudent.telegram_phone_number == phone,
            EducationStudent.status == "active",
        )
        .with_for_update()
    )
    if student is None or (identity and identity.student_id != student.id):
        return DENIED, CONTACT_KEYBOARD
    # A different account already linked to this student must be revoked by staff first.
    other = await session.scalar(
        select(EducationStudentIdentity.id).where(
            EducationStudentIdentity.tenant_id == agent.tenant_id,
            EducationStudentIdentity.workspace_id == agent.workspace_id,
            EducationStudentIdentity.student_id == student.id,
            EducationStudentIdentity.identity_type == "telegram",
            EducationStudentIdentity.normalized_identifier != sender,
            EducationStudentIdentity.status == "verified",
        )
    )
    if other:
        return DENIED, CONTACT_KEYBOARD
    try:
        async with session.begin_nested():
            if identity is None:
                identity = EducationStudentIdentity(
                    tenant_id=agent.tenant_id,
                    workspace_id=agent.workspace_id,
                    student_id=student.id,
                    identity_type="telegram",
                    identifier=sender,
                    normalized_identifier=sender,
                )
                session.add(identity)
            identity.status = "verified"
            identity.is_primary = True
            identity.verified_at = datetime.now(UTC)
            await session.flush()
    except IntegrityError:
        return DENIED, CONTACT_KEYBOARD
    return (
        "Phone number verified. You can now ask a course question. Access depends on your active enrollment.",
        {"remove_keyboard": True},
    )
