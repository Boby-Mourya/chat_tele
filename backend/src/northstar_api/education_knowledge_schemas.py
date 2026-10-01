from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field, model_validator

from northstar_api.schemas import APIModel


class EducationKnowledgeScopeRef(APIModel):
    course_id: UUID
    curriculum_id: UUID | None = None
    paper_id: UUID | None = None
    batch_id: UUID | None = None
    selected_block_ids: list[str] = Field(default_factory=list, max_length=10_000)
    topic_ids: list[str] = Field(default_factory=list, max_length=1_000)
    material_type: str = Field(default="notes", min_length=1, max_length=40)


class EducationKnowledgeScopeReplace(APIModel):
    scopes: list[EducationKnowledgeScopeRef] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique_pairs(self) -> EducationKnowledgeScopeReplace:
        pairs = {
            (item.course_id, item.curriculum_id, item.paper_id, item.batch_id)
            for item in self.scopes
        }
        if len(pairs) != len(self.scopes):
            raise ValueError("education knowledge scopes must be unique")
        return self


class EducationKnowledgeScopeOut(EducationKnowledgeScopeRef):
    id: UUID
    source_id: UUID | None = None
    source_version_id: UUID | None = None
    fact_id: UUID | None = None
    agent_id: UUID
    workspace_id: UUID
    extraction_revision: int
    mapping_revision: int
    assignment_revision: int
    requires_release: bool
    approval_status: str
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    published_at: datetime | None = None
    withdrawn_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
