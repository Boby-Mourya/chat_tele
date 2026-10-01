from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import Field, model_validator

from northstar_api.education_enrollments import EnrollmentStatus
from northstar_api.schemas import APIModel


class EnrollmentCreate(APIModel):
    student_id: UUID
    course_id: UUID
    batch_id: UUID
    agent_id: UUID
    curriculum_id: UUID | None = None
    all_papers: bool = True
    paper_ids: list[UUID] = Field(default_factory=list)
    starts_on: date | None = None
    ends_on: date | None = None
    status: EnrollmentStatus = EnrollmentStatus.PENDING

    @model_validator(mode="after")
    def valid_date_range(self) -> EnrollmentCreate:
        if self.starts_on and self.ends_on and self.ends_on < self.starts_on:
            raise ValueError("enrollment end date cannot be before start date")
        return self


class EnrollmentPatch(APIModel):
    course_id: UUID | None = None
    batch_id: UUID | None = None
    agent_id: UUID | None = None
    curriculum_id: UUID | None = None
    all_papers: bool | None = None
    paper_ids: list[UUID] | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    status: EnrollmentStatus | None = None


class EnrollmentOut(APIModel):
    id: UUID
    tenant_id: UUID
    workspace_id: UUID
    student_id: UUID
    course_id: UUID
    curriculum_id: UUID | None
    batch_id: UUID
    agent_id: UUID
    all_papers: bool
    paper_ids: list[UUID]
    authorization_revision: int
    starts_on: date | None
    ends_on: date | None
    status: EnrollmentStatus
    created_at: datetime
    updated_at: datetime
