from __future__ import annotations

import re
from datetime import date
from typing import Any, Literal

from pydantic import EmailStr, Field, field_validator, model_validator

from northstar_api.education_student_identities import StudentIdentityType
from northstar_api.schemas import APIModel

_STUDENT_NUMBER = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,79}$")
_CODE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,39}$")


def _normalized_code(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().upper()
    if not _CODE.fullmatch(normalized):
        raise ValueError("code must use letters, numbers, dots, dashes, or underscores")
    return normalized


class StudentImportRow(APIModel):
    student_number: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=2, max_length=160)
    email: EmailStr | None = None
    identity_type: StudentIdentityType | None = None
    identifier: str | None = Field(default=None, max_length=320)
    identity_verified: bool = False
    course_code: str | None = Field(default=None, max_length=40)
    batch_code: str | None = Field(default=None, max_length=40)
    agent_public_id: str | None = Field(default=None, max_length=48)
    enrollment_status: Literal["pending", "active"] = "active"
    starts_on: date | None = None
    ends_on: date | None = None
    custom_fields: dict[str, Any] = Field(default_factory=dict)

    @field_validator("student_number")
    @classmethod
    def normalize_student_number(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not _STUDENT_NUMBER.fullmatch(normalized):
            raise ValueError("student ID must use letters, numbers, dots, dashes, or underscores")
        return normalized

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.strip().split())
        if len(normalized) < 2:
            raise ValueError("student name must contain at least 2 characters")
        return normalized

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr | None) -> str | None:
        return str(value).strip().lower() if value is not None else None

    @field_validator("identifier", "agent_public_id")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("course_code", "batch_code")
    @classmethod
    def normalize_code(cls, value: str | None) -> str | None:
        return _normalized_code(value)

    @field_validator("custom_fields")
    @classmethod
    def validate_custom_fields(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(value) > 50:
            raise ValueError("custom fields cannot contain more than 50 entries")
        normalized: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = raw_key.strip()
            if not key or len(key) > 80:
                raise ValueError("custom field names must contain 1 to 80 characters")
            if isinstance(raw_value, (dict, list)):
                raise ValueError("custom field values must be scalar values")
            normalized[key] = raw_value.strip() if isinstance(raw_value, str) else raw_value
        return normalized

    @model_validator(mode="after")
    def validate_optional_groups(self) -> StudentImportRow:
        if (self.identity_type is None) != (self.identifier is None):
            raise ValueError("identity type and identifier must be provided together")
        if self.identity_verified and self.identity_type is None:
            raise ValueError("identity_verified requires an identity")
        enrollment_values = [self.course_code, self.batch_code, self.agent_public_id]
        if any(value is not None for value in enrollment_values) and not all(
            value is not None for value in enrollment_values
        ):
            raise ValueError("course code, batch code, and Agent ID must be provided together")
        if self.course_code is None and (self.starts_on is not None or self.ends_on is not None):
            raise ValueError("enrollment dates require Course, Batch, and Agent assignment")
        if self.starts_on is not None and self.ends_on is not None and self.ends_on < self.starts_on:
            raise ValueError("enrollment end date cannot be before start date")
        return self


class StudentImportPayload(APIModel):
    rows: list[StudentImportRow] = Field(min_length=1, max_length=500)


class StudentImportRowPreview(APIModel):
    row_number: int
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    row: StudentImportRow


class StudentImportPreview(APIModel):
    total_rows: int
    valid_rows: int
    invalid_rows: int
    rows: list[StudentImportRowPreview]


class StudentImportCommitResult(APIModel):
    created_students: int
    created_identities: int
    created_enrollments: int


class StudentImportCommitResponse(APIModel):
    committed: bool
    preview: StudentImportPreview
    result: StudentImportCommitResult | None = None
