from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import EmailStr, Field, field_validator

from northstar_api.education_students import StudentStatus
from northstar_api.schemas import APIModel

_STUDENT_NUMBER = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,79}$")


def _normalize_student_number(value: str) -> str:
    normalized = value.strip().upper()
    if not _STUDENT_NUMBER.fullmatch(normalized):
        raise ValueError("student ID must use letters, numbers, dots, dashes, or underscores")
    return normalized


def _normalize_name(value: str) -> str:
    normalized = " ".join(value.strip().split())
    if len(normalized) < 2:
        raise ValueError("student name must contain at least 2 characters")
    return normalized


def _normalize_custom_fields(value: dict[str, Any]) -> dict[str, Any]:
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


def _normalize_email(value: EmailStr | None) -> str | None:
    return str(value).strip().lower() if value is not None else None


class StudentCreate(APIModel):
    student_number: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=2, max_length=160)
    email: EmailStr | None = None
    whatsapp_number: str | None = Field(default=None, max_length=40)
    whatsapp_verified: bool = False
    telegram_phone_verified: bool = False
    telegram_phone_number: str | None = Field(default=None, max_length=40)
    telegram_user_id: str | None = Field(default=None, max_length=20)
    telegram_verified: bool = False
    preferred_language: str = Field(default="English", min_length=2, max_length=80)

    @field_validator("whatsapp_number", "telegram_phone_number")
    @classmethod
    def valid_whatsapp(cls, value: str | None) -> str | None:
        from northstar_api.education_student_identities import StudentIdentityType
        from northstar_api.services.student_identity import normalize_student_identity

        return (
            normalize_student_identity(StudentIdentityType.WHATSAPP, value)
            if value and value.strip()
            else None
        )

    @field_validator("telegram_user_id")
    @classmethod
    def valid_telegram_user_id(cls, value: str | None) -> str | None:
        from northstar_api.education_student_identities import StudentIdentityType
        from northstar_api.services.student_identity import normalize_student_identity

        return (
            normalize_student_identity(StudentIdentityType.TELEGRAM, value)
            if value and value.strip()
            else None
        )

    custom_fields: dict[str, Any] = Field(default_factory=dict)

    @field_validator("student_number")
    @classmethod
    def valid_student_number(cls, value: str) -> str:
        return _normalize_student_number(value)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        return _normalize_name(value)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr | None) -> str | None:
        return _normalize_email(value)

    @field_validator("custom_fields")
    @classmethod
    def valid_custom_fields(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _normalize_custom_fields(value)

    @field_validator("preferred_language")
    @classmethod
    def normalize_language(cls, value: str) -> str:
        return " ".join(value.strip().split())


class StudentPatch(APIModel):
    whatsapp_number: str | None = Field(default=None, max_length=40)
    whatsapp_verified: bool = False
    telegram_phone_verified: bool = False
    telegram_phone_number: str | None = Field(default=None, max_length=40)
    telegram_user_id: str | None = Field(default=None, max_length=20)
    telegram_verified: bool = False
    preferred_language: str | None = Field(default=None, min_length=2, max_length=80)
    valid_whatsapp = field_validator("whatsapp_number", "telegram_phone_number")(StudentCreate.valid_whatsapp.__func__)
    valid_telegram_user_id = field_validator("telegram_user_id")(StudentCreate.valid_telegram_user_id.__func__)

    student_number: str | None = Field(default=None, min_length=1, max_length=80)
    name: str | None = Field(default=None, min_length=2, max_length=160)
    email: EmailStr | None = None
    custom_fields: dict[str, Any] | None = None
    status: StudentStatus | None = None

    @field_validator("student_number")
    @classmethod
    def valid_student_number(cls, value: str | None) -> str | None:
        return _normalize_student_number(value) if value is not None else None

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str | None) -> str | None:
        return _normalize_name(value) if value is not None else None

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr | None) -> str | None:
        return _normalize_email(value)

    @field_validator("custom_fields")
    @classmethod
    def valid_custom_fields(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        return _normalize_custom_fields(value) if value is not None else None

    @field_validator("preferred_language")
    @classmethod
    def normalize_language(cls, value: str | None) -> str | None:
        return " ".join(value.strip().split()) if value is not None else None


class StudentOut(APIModel):
    whatsapp_number: str | None = None
    whatsapp_verified: bool = False
    telegram_phone_verified: bool = False
    telegram_phone_number: str | None = None
    telegram_user_id: str | None = None
    telegram_verified: bool = False
    id: UUID
    tenant_id: UUID
    workspace_id: UUID
    student_number: str
    name: str
    email: EmailStr | None
    preferred_language: str
    custom_fields: dict[str, Any]
    status: StudentStatus
    created_at: datetime
    updated_at: datetime
