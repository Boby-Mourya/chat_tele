from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import EmailStr, Field, field_validator

from northstar_api.education_access_requests import EducationAccessRequestStatus
from northstar_api.education_student_identities import StudentIdentityType
from northstar_api.schemas import APIModel

_STUDENT_NUMBER = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,79}$")


class EducationAccessRequestCreate(APIModel):
    agent_public_id: str = Field(min_length=5, max_length=48)
    student_number: str = Field(min_length=1, max_length=80)
    email: EmailStr
    identity_type: StudentIdentityType
    identifier: str = Field(min_length=1, max_length=320)
    message: str | None = Field(default=None, max_length=1000)

    @field_validator("student_number")
    @classmethod
    def normalize_student_number(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not _STUDENT_NUMBER.fullmatch(normalized):
            raise ValueError("student ID must use letters, numbers, dots, dashes, or underscores")
        return normalized

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.strip().split())
        return normalized or None


class EducationAccessRequestAccepted(APIModel):
    accepted: bool = True
    request_id: UUID


class EducationAccessRequestOut(APIModel):
    id: UUID
    tenant_id: UUID
    workspace_id: UUID
    agent_id: UUID
    student_id: UUID | None
    enrollment_id: UUID | None
    student_number: str
    email: EmailStr | None
    identity_type: StudentIdentityType
    normalized_identifier: str
    message: str | None
    status: EducationAccessRequestStatus
    reviewed_by_user_id: UUID | None
    reviewed_at: datetime | None
    resolution_note: str | None
    created_at: datetime
    updated_at: datetime


class EducationAccessRequestReview(APIModel):
    action: Literal["approve", "deny"]
    student_id: UUID | None = None
    enrollment_id: UUID | None = None
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.strip().split())
        return normalized or None
