from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.education_student_identities import (
    EducationStudentIdentity,
    StudentIdentityStatus,
    StudentIdentityType,
)
from northstar_api.education_students import EducationStudent, StudentStatus

_PHONE_CLEANUP = re.compile(r"[\s().-]+")
_PHONE_E164 = re.compile(r"^\+[1-9]\d{7,14}$")
_TELEGRAM_USER_ID = re.compile(r"^[1-9]\d{4,19}$")


def normalize_student_identity(identity_type: StudentIdentityType, identifier: str) -> str:
    """Return the canonical identifier used for uniqueness and later lookups."""

    value = identifier.strip()
    if identity_type in {StudentIdentityType.WHATSAPP, StudentIdentityType.ALTERNATE_PHONE}:
        value = _PHONE_CLEANUP.sub("", value)
        if value.startswith("00"):
            value = f"+{value[2:]}"
        if not _PHONE_E164.fullmatch(value):
            raise ValueError("phone identity must be a valid international E.164 number")
        return value

    if identity_type is StudentIdentityType.TELEGRAM:
        if not _TELEGRAM_USER_ID.fullmatch(value):
            raise ValueError("Telegram identity must be a numeric Telegram user ID")
        return value

    if identity_type is StudentIdentityType.WEBSITE_LOGIN:
        value = value.lower()
        if len(value) < 2 or len(value) > 320 or any(character.isspace() for character in value):
            raise ValueError("website login identity must contain 2 to 320 characters without spaces")
        return value

    raise ValueError("unsupported student identity type")


async def find_workspace_student_identity(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    identity_type: StudentIdentityType,
    identifier: str,
    verified_only: bool = True,
) -> EducationStudentIdentity | None:
    """Resolve a Student identity inside a tenant/workspace boundary.

    This helper establishes identity only. It is deliberately not Education authorization:
    callers must still validate the Agent and a matching active Enrollment before exposing
    private course or batch knowledge.
    """

    normalized = normalize_student_identity(identity_type, identifier)
    conditions = [
        EducationStudentIdentity.tenant_id == tenant_id,
        EducationStudentIdentity.workspace_id == workspace_id,
        EducationStudentIdentity.identity_type == identity_type.value,
        EducationStudentIdentity.normalized_identifier == normalized,
        EducationStudent.status == StudentStatus.ACTIVE.value,
    ]
    if verified_only:
        conditions.append(EducationStudentIdentity.status == StudentIdentityStatus.VERIFIED.value)
    else:
        conditions.append(EducationStudentIdentity.status != StudentIdentityStatus.REVOKED.value)

    identity = await session.scalar(
        select(EducationStudentIdentity)
        .join(EducationStudent, EducationStudent.id == EducationStudentIdentity.student_id)
        .where(*conditions)
    )
    return identity
