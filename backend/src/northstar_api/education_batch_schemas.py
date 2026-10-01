from __future__ import annotations

import re
from datetime import date, datetime
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from northstar_api.education_batches import BatchStatus
from northstar_api.schemas import APIModel

_BATCH_CODE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,39}$")


def _normalize_code(value: str) -> str:
    normalized = value.strip().upper()
    if not _BATCH_CODE.fullmatch(normalized):
        raise ValueError("batch code must use letters, numbers, dots, dashes, or underscores")
    return normalized


def _normalize_name(value: str) -> str:
    normalized = value.strip()
    if len(normalized) < 2:
        raise ValueError("batch name must contain at least 2 characters")
    return normalized


class BatchCreate(APIModel):
    course_id: UUID
    curriculum_id: UUID | None = None
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=2, max_length=160)
    description: str = Field(default="", max_length=2000)
    starts_on: date | None = None
    ends_on: date | None = None

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

    @model_validator(mode="after")
    def valid_date_range(self) -> BatchCreate:
        if self.starts_on and self.ends_on and self.ends_on < self.starts_on:
            raise ValueError("batch end date cannot be before start date")
        return self


class BatchPatch(APIModel):
    code: str | None = Field(default=None, min_length=1, max_length=40)
    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    starts_on: date | None = None
    ends_on: date | None = None
    status: BatchStatus | None = None

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


class BatchOut(APIModel):
    id: UUID
    tenant_id: UUID
    workspace_id: UUID
    course_id: UUID
    curriculum_id: UUID | None
    code: str
    name: str
    description: str
    starts_on: date | None
    ends_on: date | None
    status: BatchStatus
    created_at: datetime
    updated_at: datetime
