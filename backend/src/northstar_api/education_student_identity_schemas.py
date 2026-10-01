from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from northstar_api.education_student_identities import StudentIdentityStatus, StudentIdentityType
from northstar_api.schemas import APIModel
from northstar_api.services.student_identity import normalize_student_identity


def _normalize_label(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.strip().split())
    return normalized or None


class StudentIdentityCreate(APIModel):
    identity_type: StudentIdentityType
    identifier: str = Field(min_length=1, max_length=320)
    label: str | None = Field(default=None, max_length=80)
    status: StudentIdentityStatus = StudentIdentityStatus.PENDING
    is_primary: bool = False

    @field_validator("label")
    @classmethod
    def valid_label(cls, value: str | None) -> str | None:
        return _normalize_label(value)

    @model_validator(mode="after")
    def normalize_identifier(self) -> StudentIdentityCreate:
        if self.status is StudentIdentityStatus.REVOKED:
            raise ValueError("a new identity cannot start in revoked status")
        self.identifier = normalize_student_identity(self.identity_type, self.identifier)
        return self


class StudentIdentityPatch(APIModel):
    label: str | None = Field(default=None, max_length=80)
    status: StudentIdentityStatus | None = None
    is_primary: bool | None = None

    @field_validator("label")
    @classmethod
    def valid_label(cls, value: str | None) -> str | None:
        return _normalize_label(value)


class StudentIdentityOut(APIModel):
    id: UUID
    tenant_id: UUID
    workspace_id: UUID
    student_id: UUID
    identity_type: StudentIdentityType
    identifier: str
    normalized_identifier: str
    label: str | None
    status: StudentIdentityStatus
    is_primary: bool
    verified_at: datetime | None
    created_at: datetime
    updated_at: datetime
