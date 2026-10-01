from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
import smtplib
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from email.message import EmailMessage
from uuid import UUID

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.agent_purpose import AgentPurpose, get_agent_purpose
from northstar_api.config import get_settings
from northstar_api.education import CourseStatus, EducationCourse
from northstar_api.education_access_recovery import EducationAccessRecoveryChallenge
from northstar_api.education_batches import BatchStatus, EducationBatch
from northstar_api.education_enrollments import EducationEnrollment, EnrollmentStatus
from northstar_api.education_student_identities import (
    EducationStudentIdentity,
    StudentIdentityStatus,
    StudentIdentityType,
)
from northstar_api.education_students import EducationStudent, StudentStatus
from northstar_api.email_config import EmailSettings, get_email_settings
from northstar_api.models import Agent, AgentStatus
from northstar_api.services.outbox import enqueue_event
from northstar_api.services.student_identity import normalize_student_identity

logger = structlog.get_logger(__name__)
RECOVERY_TTL_SECONDS = 600
RECOVERY_MAX_ATTEMPTS = 5


class EducationAccessRecoveryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class IssuedEducationRecovery:
    request_id: UUID
    code: str
    email: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class EducationRecoveryVerification:
    verified: bool
    already_verified: bool = False


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _code_digest(request_id: UUID, code: str) -> str:
    key = get_settings().jwt_secret.get_secret_value().encode("utf-8")
    payload = f"education-access-recovery:{request_id}:{code}".encode()
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def _new_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _within(value: date, starts_on: date | None, ends_on: date | None) -> bool:
    if starts_on is not None and value < starts_on:
        return False
    if ends_on is not None and value > ends_on:
        return False
    return True


async def _valid_enrollment(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    agent_id: UUID,
    student_id: UUID,
    enrollment_id: UUID | None = None,
) -> EducationEnrollment | None:
    conditions = [
        EducationEnrollment.tenant_id == tenant_id,
        EducationEnrollment.workspace_id == workspace_id,
        EducationEnrollment.agent_id == agent_id,
        EducationEnrollment.student_id == student_id,
        EducationEnrollment.status == EnrollmentStatus.ACTIVE.value,
        EducationCourse.tenant_id == tenant_id,
        EducationCourse.workspace_id == workspace_id,
        EducationCourse.status == CourseStatus.ACTIVE.value,
        EducationBatch.tenant_id == tenant_id,
        EducationBatch.workspace_id == workspace_id,
        EducationBatch.status == BatchStatus.ACTIVE.value,
        EducationBatch.course_id == EducationEnrollment.course_id,
    ]
    if enrollment_id is not None:
        conditions.append(EducationEnrollment.id == enrollment_id)
    rows = (
        await session.execute(
            select(EducationEnrollment, EducationBatch)
            .join(EducationCourse, EducationCourse.id == EducationEnrollment.course_id)
            .join(EducationBatch, EducationBatch.id == EducationEnrollment.batch_id)
            .where(*conditions)
            .order_by(EducationEnrollment.updated_at.desc())
        )
    ).all()
    from northstar_api.services.workspace_dates import workspace_today

    today = await workspace_today(session, tenant_id=tenant_id, workspace_id=workspace_id)
    valid = [
        enrollment
        for enrollment, batch in rows
        if _within(today, enrollment.starts_on, enrollment.ends_on)
        and _within(today, batch.starts_on, batch.ends_on)
    ]
    return valid[0] if len(valid) == 1 else None


async def issue_education_access_recovery(
    session: AsyncSession,
    *,
    request_id: UUID,
    agent_public_id: str,
    student_number: str,
    email: str,
    identity_type: StudentIdentityType,
    identifier: str,
) -> IssuedEducationRecovery | None:
    """Issue a recovery challenge without revealing why an invalid request was rejected."""

    try:
        normalized_identifier = normalize_student_identity(identity_type, identifier)
    except ValueError:
        return None

    agent = await session.scalar(
        select(Agent).where(
            Agent.public_id == agent_public_id,
            Agent.status == AgentStatus.ACTIVE,
            Agent.deleted_at.is_(None),
        )
    )
    if agent is None:
        return None
    purpose = await get_agent_purpose(
        session,
        tenant_id=agent.tenant_id,
        workspace_id=agent.workspace_id,
        agent_id=agent.id,
    )
    if purpose is not AgentPurpose.EDUCATION:
        return None

    normalized_email = email.strip().lower()
    student = await session.scalar(
        select(EducationStudent)
        .where(
            EducationStudent.tenant_id == agent.tenant_id,
            EducationStudent.workspace_id == agent.workspace_id,
            EducationStudent.student_number == student_number,
            func.lower(EducationStudent.email) == normalized_email,
            EducationStudent.status == StudentStatus.ACTIVE.value,
        )
        .with_for_update()
    )
    if student is None or not student.email:
        return None

    enrollment = await _valid_enrollment(
        session,
        tenant_id=agent.tenant_id,
        workspace_id=agent.workspace_id,
        agent_id=agent.id,
        student_id=student.id,
    )
    if enrollment is None:
        return None

    existing_identity = await session.scalar(
        select(EducationStudentIdentity).where(
            EducationStudentIdentity.tenant_id == agent.tenant_id,
            EducationStudentIdentity.workspace_id == agent.workspace_id,
            EducationStudentIdentity.identity_type == identity_type.value,
            EducationStudentIdentity.normalized_identifier == normalized_identifier,
        )
    )
    if existing_identity is not None:
        if existing_identity.student_id != student.id:
            return None
        if existing_identity.status in {
            StudentIdentityStatus.VERIFIED.value,
            StudentIdentityStatus.REVOKED.value,
        }:
            return None

    now = datetime.now(UTC)
    await session.execute(
        update(EducationAccessRecoveryChallenge)
        .where(
            EducationAccessRecoveryChallenge.tenant_id == agent.tenant_id,
            EducationAccessRecoveryChallenge.workspace_id == agent.workspace_id,
            EducationAccessRecoveryChallenge.agent_id == agent.id,
            EducationAccessRecoveryChallenge.student_id == student.id,
            EducationAccessRecoveryChallenge.identity_type == identity_type.value,
            EducationAccessRecoveryChallenge.normalized_identifier == normalized_identifier,
            EducationAccessRecoveryChallenge.consumed_at.is_(None),
        )
        .values(consumed_at=now, updated_at=now)
    )

    code = _new_code()
    expires_at = now + timedelta(seconds=RECOVERY_TTL_SECONDS)
    challenge = EducationAccessRecoveryChallenge(
        id=request_id,
        tenant_id=agent.tenant_id,
        workspace_id=agent.workspace_id,
        agent_id=agent.id,
        student_id=student.id,
        enrollment_id=enrollment.id,
        identity_type=identity_type.value,
        normalized_identifier=normalized_identifier,
        delivery_email=normalized_email,
        code_digest=_code_digest(request_id, code),
        failed_attempts=0,
        max_attempts=RECOVERY_MAX_ATTEMPTS,
        expires_at=expires_at,
    )
    session.add(challenge)
    await session.flush()
    enqueue_event(
        session,
        tenant_id=agent.tenant_id,
        aggregate_type="education_access_recovery",
        aggregate_id=challenge.id,
        event_type="education.access_recovery.started.v1",
        payload={
            "requestId": str(challenge.id),
            "workspaceId": str(agent.workspace_id),
            "agentId": str(agent.id),
            "studentId": str(student.id),
            "enrollmentId": str(enrollment.id),
            "identityType": identity_type.value,
        },
    )
    return IssuedEducationRecovery(
        request_id=challenge.id,
        code=code,
        email=normalized_email,
        expires_at=expires_at,
    )


async def verify_education_access_recovery(
    session: AsyncSession,
    *,
    request_id: UUID,
    code: str,
) -> EducationRecoveryVerification:
    challenge = await session.scalar(
        select(EducationAccessRecoveryChallenge)
        .where(EducationAccessRecoveryChallenge.id == request_id)
        .with_for_update()
    )
    if challenge is None:
        raise EducationAccessRecoveryError("Verification code is invalid or expired")

    now = datetime.now(UTC)
    if challenge.consumed_at is not None or _aware(challenge.expires_at) <= now:
        raise EducationAccessRecoveryError("Verification code is invalid or expired")
    if challenge.failed_attempts >= challenge.max_attempts:
        challenge.consumed_at = now
        raise EducationAccessRecoveryError("Verification code is invalid or expired")

    expected = _code_digest(challenge.id, code)
    if not hmac.compare_digest(challenge.code_digest, expected):
        challenge.failed_attempts += 1
        if challenge.failed_attempts >= challenge.max_attempts:
            challenge.consumed_at = now
        await session.flush()
        raise EducationAccessRecoveryError("Verification code is invalid or expired")

    agent = await session.get(Agent, challenge.agent_id)
    student = await session.get(EducationStudent, challenge.student_id)
    if (
        agent is None
        or agent.tenant_id != challenge.tenant_id
        or agent.workspace_id != challenge.workspace_id
        or agent.deleted_at is not None
        or agent.status != AgentStatus.ACTIVE
        or student is None
        or student.tenant_id != challenge.tenant_id
        or student.workspace_id != challenge.workspace_id
        or student.status != StudentStatus.ACTIVE.value
    ):
        challenge.consumed_at = now
        raise EducationAccessRecoveryError("Verification code is invalid or expired")
    purpose = await get_agent_purpose(
        session,
        tenant_id=challenge.tenant_id,
        workspace_id=challenge.workspace_id,
        agent_id=challenge.agent_id,
    )
    if purpose is not AgentPurpose.EDUCATION:
        challenge.consumed_at = now
        raise EducationAccessRecoveryError("Verification code is invalid or expired")

    enrollment = await _valid_enrollment(
        session,
        tenant_id=challenge.tenant_id,
        workspace_id=challenge.workspace_id,
        agent_id=challenge.agent_id,
        student_id=challenge.student_id,
        enrollment_id=challenge.enrollment_id,
    )
    if enrollment is None:
        challenge.consumed_at = now
        raise EducationAccessRecoveryError("Verification code is invalid or expired")

    identity = await session.scalar(
        select(EducationStudentIdentity).where(
            EducationStudentIdentity.tenant_id == challenge.tenant_id,
            EducationStudentIdentity.workspace_id == challenge.workspace_id,
            EducationStudentIdentity.identity_type == challenge.identity_type,
            EducationStudentIdentity.normalized_identifier == challenge.normalized_identifier,
        )
    )
    if identity is not None and identity.student_id != challenge.student_id:
        challenge.consumed_at = now
        raise EducationAccessRecoveryError("Verification code is invalid or expired")
    if identity is not None and identity.status == StudentIdentityStatus.REVOKED.value:
        challenge.consumed_at = now
        raise EducationAccessRecoveryError("Verification code is invalid or expired")

    already_verified = bool(
        identity is not None and identity.status == StudentIdentityStatus.VERIFIED.value
    )
    if identity is None:
        has_other = await session.scalar(
            select(EducationStudentIdentity.id).where(
                EducationStudentIdentity.tenant_id == challenge.tenant_id,
                EducationStudentIdentity.workspace_id == challenge.workspace_id,
                EducationStudentIdentity.student_id == challenge.student_id,
                EducationStudentIdentity.identity_type == challenge.identity_type,
                EducationStudentIdentity.status != StudentIdentityStatus.REVOKED.value,
            )
        )
        candidate = EducationStudentIdentity(
            tenant_id=challenge.tenant_id,
            workspace_id=challenge.workspace_id,
            student_id=challenge.student_id,
            identity_type=challenge.identity_type,
            identifier=challenge.normalized_identifier,
            normalized_identifier=challenge.normalized_identifier,
            label="Verified through access recovery",
            status=StudentIdentityStatus.VERIFIED.value,
            is_primary=has_other is None,
            verified_at=now,
        )
        try:
            async with session.begin_nested():
                session.add(candidate)
                await session.flush()
            identity = candidate
        except IntegrityError:
            # Another verification may have claimed this unique workspace/type/identifier
            # while this challenge was in flight. Re-read the winner and only continue
            # when it belongs to this same Student; never turn a uniqueness race into
            # an ownership bypass or an internal server error.
            identity = await session.scalar(
                select(EducationStudentIdentity).where(
                    EducationStudentIdentity.tenant_id == challenge.tenant_id,
                    EducationStudentIdentity.workspace_id == challenge.workspace_id,
                    EducationStudentIdentity.identity_type == challenge.identity_type,
                    EducationStudentIdentity.normalized_identifier == challenge.normalized_identifier,
                )
            )
            if (
                identity is None
                or identity.student_id != challenge.student_id
                or identity.status == StudentIdentityStatus.REVOKED.value
            ):
                challenge.consumed_at = now
                raise EducationAccessRecoveryError("Verification code is invalid or expired") from None
            already_verified = identity.status == StudentIdentityStatus.VERIFIED.value
            if not already_verified:
                identity.status = StudentIdentityStatus.VERIFIED.value
                identity.verified_at = now
                await session.flush()
    elif not already_verified:
        identity.status = StudentIdentityStatus.VERIFIED.value
        identity.verified_at = now
        await session.flush()

    if not already_verified:
        enqueue_event(
            session,
            tenant_id=challenge.tenant_id,
            aggregate_type="education_student_identity",
            aggregate_id=identity.id,
            event_type="education.student_identity.verified.v1",
            payload={
                "identityId": str(identity.id),
                "studentId": str(challenge.student_id),
                "workspaceId": str(challenge.workspace_id),
                "identityType": challenge.identity_type,
                "source": "access_recovery",
            },
        )

    challenge.consumed_at = now
    enqueue_event(
        session,
        tenant_id=challenge.tenant_id,
        aggregate_type="education_access_recovery",
        aggregate_id=challenge.id,
        event_type="education.access_recovery.completed.v1",
        payload={
            "requestId": str(challenge.id),
            "workspaceId": str(challenge.workspace_id),
            "agentId": str(challenge.agent_id),
            "studentId": str(challenge.student_id),
            "enrollmentId": str(challenge.enrollment_id),
            "identityId": str(identity.id),
            "identityType": challenge.identity_type,
            "alreadyVerified": already_verified,
        },
    )
    await session.flush()
    return EducationRecoveryVerification(verified=True, already_verified=already_verified)


def _smtp_send(message: EmailMessage, settings: EmailSettings) -> None:
    if settings.smtp_ssl:
        client: smtplib.SMTP = smtplib.SMTP_SSL(
            settings.smtp_host,
            settings.smtp_port,
            timeout=settings.smtp_timeout_seconds,
        )
    else:
        client = smtplib.SMTP(
            settings.smtp_host,
            settings.smtp_port,
            timeout=settings.smtp_timeout_seconds,
        )
    try:
        if settings.smtp_starttls:
            client.starttls()
        if settings.smtp_username:
            client.login(
                settings.smtp_username,
                settings.smtp_password.get_secret_value() if settings.smtp_password else "",
            )
        client.send_message(message)
    finally:
        try:
            client.quit()
        except smtplib.SMTPException:
            client.close()


async def send_education_recovery_email(email: str, code: str) -> None:
    settings = get_email_settings()
    if settings.email_delivery_mode == "log":
        if get_settings().is_production:
            raise EducationAccessRecoveryError("Education recovery email delivery is not configured")
        # Deliberately do not log the OTP. Development callers can inject a mailer in tests.
        logger.info("education_access_recovery_email_development", email=email)
        return

    message = EmailMessage()
    message["Subject"] = "Your Northstar education access verification code"
    message["From"] = f"{settings.email_from_name} <{settings.email_from_address}>"
    message["To"] = email
    message.set_content(
        "Use this one-time code to verify your student identity and restore education access:\n\n"
        f"{code}\n\n"
        "This code expires in 10 minutes. If you did not request access recovery, ignore this email."
    )
    await asyncio.to_thread(_smtp_send, message, settings)
