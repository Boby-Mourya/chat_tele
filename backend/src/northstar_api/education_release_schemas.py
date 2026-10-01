from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from northstar_api.schemas import APIModel


class EducationReleaseCreate(APIModel):
    agent_id: UUID
    course_id: UUID
    curriculum_id: UUID
    assignment_ids: list[UUID] = Field(min_length=1, max_length=10_000)


class EducationReleaseActivate(APIModel):
    index_verified: bool


class EducationReleaseOut(APIModel):
    id: UUID
    agent_id: UUID
    course_id: UUID
    curriculum_id: UUID
    revision: int
    status: str
    manifest: dict[str, object]
    index_verified: bool
    activated_by: UUID | None = None
    activated_at: datetime | None = None
    created_at: datetime
