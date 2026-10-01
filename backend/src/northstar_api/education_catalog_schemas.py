from __future__ import annotations

import re
from datetime import date, datetime
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from northstar_api.education_curricula import CurriculumStatus
from northstar_api.education_papers import PaperStatus
from northstar_api.schemas import APIModel

_CODE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,79}$")


def _code(value: str) -> str:
    normalized = value.strip().upper()
    if not _CODE.fullmatch(normalized):
        raise ValueError("code must use letters, numbers, dots, dashes, or underscores")
    return normalized


def _text(value: str) -> str:
    return " ".join(value.strip().split())


def _aliases(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = _text(raw)
        if value and value.casefold() not in seen:
            seen.add(value.casefold())
            result.append(value)
    return result


class CurriculumCreate(APIModel):
    course_id: UUID
    version: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=2, max_length=160)
    description: str = Field(default="", max_length=2000)
    effective_from: date | None = None
    effective_to: date | None = None

    @field_validator("version")
    @classmethod
    def normalize_version(cls, value: str) -> str:
        return _code(value)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return _text(value)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def valid_dates(self) -> CurriculumCreate:
        if self.effective_from and self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("curriculum effective end cannot be before its start")
        return self


class CurriculumPatch(APIModel):
    version: str | None = Field(default=None, min_length=1, max_length=80)
    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    effective_from: date | None = None
    effective_to: date | None = None
    status: CurriculumStatus | None = None

    @field_validator("version")
    @classmethod
    def normalize_version(cls, value: str | None) -> str | None:
        return _code(value) if value is not None else None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        return _text(value) if value is not None else None

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class CurriculumOut(APIModel):
    id: UUID
    tenant_id: UUID
    workspace_id: UUID
    course_id: UUID
    version: str
    name: str
    description: str
    effective_from: date | None
    effective_to: date | None
    status: CurriculumStatus
    created_at: datetime
    updated_at: datetime


class PaperCreate(APIModel):
    curriculum_id: UUID
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=2, max_length=160)
    description: str = Field(default="", max_length=2000)
    aliases: list[str] = Field(default_factory=list, max_length=30)
    sequence: int = Field(default=0, ge=0, le=1000)

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return _code(value)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return _text(value)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        return value.strip()

    @field_validator("aliases")
    @classmethod
    def normalize_aliases(cls, values: list[str]) -> list[str]:
        return _aliases(values)


class PaperPatch(APIModel):
    code: str | None = Field(default=None, min_length=1, max_length=40)
    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    aliases: list[str] | None = Field(default=None, max_length=30)
    sequence: int | None = Field(default=None, ge=0, le=1000)
    status: PaperStatus | None = None

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str | None) -> str | None:
        return _code(value) if value is not None else None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        return _text(value) if value is not None else None

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("aliases")
    @classmethod
    def normalize_aliases(cls, values: list[str] | None) -> list[str] | None:
        return _aliases(values) if values is not None else None


class PaperOut(APIModel):
    id: UUID
    tenant_id: UUID
    workspace_id: UUID
    course_id: UUID
    curriculum_id: UUID
    code: str
    name: str
    description: str
    aliases: list[str]
    sequence: int
    status: PaperStatus
    created_at: datetime
    updated_at: datetime
