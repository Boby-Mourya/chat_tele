from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID

from pydantic import Field, field_validator

from northstar_api.education import CourseStatus
from northstar_api.schemas import APIModel

_COURSE_CODE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,39}$")


def _normalize_code(value: str) -> str:
    normalized = value.strip().upper()
    if not _COURSE_CODE.fullmatch(normalized):
        raise ValueError("course code must use letters, numbers, dots, dashes, or underscores")
    return normalized


def _normalize_name(value: str) -> str:
    normalized = value.strip()
    if len(normalized) < 2:
        raise ValueError("course name must contain at least 2 characters")
    return normalized


def _normalize_aliases(values: list[str]) -> list[str]:
    aliases: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = " ".join(raw.strip().split())
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        aliases.append(value)
    return aliases


class CourseCreate(APIModel):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=2, max_length=160)
    awarding_body: str = Field(default="", max_length=160)
    jurisdiction: str = Field(default="", max_length=80)
    aliases: list[str] = Field(default_factory=list, max_length=30)
    description: str = Field(default="", max_length=2000)

    @field_validator("code")
    @classmethod
    def valid_code(cls, value: str) -> str:
        return _normalize_code(value)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        return _normalize_name(value)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        return value.strip()

    @field_validator("awarding_body", "jurisdiction")
    @classmethod
    def normalize_optional_text(cls, value: str) -> str:
        return " ".join(value.strip().split())

    @field_validator("aliases")
    @classmethod
    def normalize_aliases(cls, values: list[str]) -> list[str]:
        return _normalize_aliases(values)


class CoursePatch(APIModel):
    code: str | None = Field(default=None, min_length=1, max_length=40)
    name: str | None = Field(default=None, min_length=2, max_length=160)
    awarding_body: str | None = Field(default=None, max_length=160)
    jurisdiction: str | None = Field(default=None, max_length=80)
    aliases: list[str] | None = Field(default=None, max_length=30)
    description: str | None = Field(default=None, max_length=2000)
    status: CourseStatus | None = None

    @field_validator("code")
    @classmethod
    def valid_code(cls, value: str | None) -> str | None:
        return _normalize_code(value) if value is not None else None

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str | None) -> str | None:
        return _normalize_name(value) if value is not None else None

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("awarding_body", "jurisdiction")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return " ".join(value.strip().split()) if value is not None else None

    @field_validator("aliases")
    @classmethod
    def normalize_aliases(cls, values: list[str] | None) -> list[str] | None:
        return _normalize_aliases(values) if values is not None else None


class CourseOut(APIModel):
    id: UUID
    tenant_id: UUID
    workspace_id: UUID
    code: str
    name: str
    awarding_body: str
    jurisdiction: str
    aliases: list[str]
    description: str
    status: CourseStatus
    created_at: datetime
    updated_at: datetime
