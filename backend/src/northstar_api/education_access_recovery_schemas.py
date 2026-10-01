from __future__ import annotations

import re
from uuid import UUID

from pydantic import EmailStr, Field, field_validator

from northstar_api.education_student_identities import StudentIdentityType
from northstar_api.schemas import APIModel

_STUDENT_NUMBER = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,79}$")
_OTP = re.compile(r"^\d{6}$")


class EducationAccessRecoveryStart(APIModel):
    agent_public_id: str = Field(min_length=5, max_length=48)
    student_number: str = Field(min_length=1, max_length=80)
    email: EmailStr
    identity_type: StudentIdentityType
    identifier: str = Field(min_length=1, max_length=320)

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


class EducationAccessRecoveryAccepted(APIModel):
    accepted: bool = True
    request_id: UUID
    expires_in_seconds: int = 600


class EducationAccessRecoveryVerify(APIModel):
    request_id: UUID
    code: str = Field(min_length=6, max_length=6)

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        if not _OTP.fullmatch(value):
            raise ValueError("verification code must contain exactly 6 digits")
        return value


class EducationAccessRecoveryResult(APIModel):
    verified: bool
    already_verified: bool = False
