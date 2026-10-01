from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import EmailStr, Field, field_validator, model_validator

from northstar_api.education_student_identities import StudentIdentityType
from northstar_api.education_student_import_schemas import StudentImportRow
from northstar_api.schemas import APIModel


class LMSStudentImportRow(APIModel):
    """Provider-neutral LMS learner record mapped into the existing Student import contract."""

    external_student_id: str = Field(min_length=1, max_length=80)
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
    external_course_id: str | None = Field(default=None, max_length=160)
    external_batch_id: str | None = Field(default=None, max_length=160)
    custom_fields: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "external_student_id",
        "identifier",
        "agent_public_id",
        "external_course_id",
        "external_batch_id",
    )
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

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

    @model_validator(mode="after")
    def validate_identity_pair(self) -> LMSStudentImportRow:
        if (self.identity_type is None) != (self.identifier is None):
            raise ValueError("identity type and identifier must be provided together")
        if self.identity_verified and self.identity_type is None:
            raise ValueError("identity_verified requires an identity")
        return self


class LMSStudentImportPayload(APIModel):
    source: str = Field(min_length=2, max_length=60)
    rows: list[LMSStudentImportRow] = Field(min_length=1, max_length=500)

    @field_validator("source")
    @classmethod
    def normalize_source(cls, value: str) -> str:
        normalized = value.strip().lower().replace(" ", "_")
        if not normalized:
            raise ValueError("LMS source is required")
        return normalized

    @model_validator(mode="after")
    def validate_existing_student_import_contract(self) -> LMSStudentImportPayload:
        # Run the canonical Student import validation while FastAPI is still
        # validating the request body. This preserves the existing 422 contract
        # for malformed IDs, Course/Batch/Agent groups, dates, and custom fields.
        _to_student_import_rows(self)
        return self


def _to_student_import_rows(payload: LMSStudentImportPayload) -> list[StudentImportRow]:
    converted: list[StudentImportRow] = []
    for row in payload.rows:
        custom_fields = dict(row.custom_fields)
        custom_fields.setdefault("lms_source", payload.source)
        custom_fields.setdefault("lms_student_id", row.external_student_id)
        if row.external_course_id:
            custom_fields.setdefault("lms_course_id", row.external_course_id)
        if row.external_batch_id:
            custom_fields.setdefault("lms_batch_id", row.external_batch_id)

        converted.append(
            StudentImportRow(
                student_number=row.external_student_id,
                name=row.name,
                email=row.email,
                identity_type=row.identity_type,
                identifier=row.identifier,
                identity_verified=row.identity_verified,
                course_code=row.course_code,
                batch_code=row.batch_code,
                agent_public_id=row.agent_public_id,
                enrollment_status=row.enrollment_status,
                starts_on=row.starts_on,
                ends_on=row.ends_on,
                custom_fields=custom_fields,
            )
        )
    return converted


def to_student_import_rows(payload: LMSStudentImportPayload) -> list[StudentImportRow]:
    """Translate LMS records into the existing, fully validated Student import format."""

    return _to_student_import_rows(payload)
