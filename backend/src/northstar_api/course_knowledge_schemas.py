"""Validated administration contracts for course-aware knowledge publication."""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


def camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(word.capitalize() for word in rest)


class Contract(BaseModel):
    model_config = ConfigDict(alias_generator=camel, populate_by_name=True, extra="forbid")


class TeachingConfiguration(Contract):
    terminology: str = Field(default="", max_length=1000)
    difficulty: str = Field(default="", max_length=100)
    syllabus_framing: str = Field(default="", max_length=1000)
    answer_format: str = Field(default="", max_length=1000)


class CurriculumCreate(Contract):
    course_id: UUID
    code: str = Field(min_length=1, max_length=80, pattern=r"^\S(?:.*\S)?$")
    name: str = Field(min_length=1, max_length=160)
    teaching_configuration: TeachingConfiguration = Field(default_factory=TeachingConfiguration)


class Topic(Contract):
    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    chapter: str = Field(default="", max_length=160)
    learning_objective: str = Field(default="", max_length=500)


class PaperCreate(Contract):
    curriculum_id: UUID
    code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    topics: list[Topic] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def distinct_topics(self) -> PaperCreate:
        if len({t.id for t in self.topics}) != len(self.topics):
            raise ValueError("Topic IDs must be distinct within this paper")
        return self


class BatchCurriculum(Contract):
    batch_id: UUID
    curriculum_id: UUID


class EnrollmentAccess(Contract):
    curriculum_id: UUID
    paper_ids: list[UUID] = Field(default_factory=list, max_length=200)
    selected_paper_id: UUID | None = None
    active: bool = True
    expected_revision: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def selected_is_authorized(self) -> EnrollmentAccess:
        if len(set(self.paper_ids)) != len(self.paper_ids):
            raise ValueError("Paper IDs must be distinct")
        if self.selected_paper_id is not None and self.selected_paper_id not in self.paper_ids:
            raise ValueError("The selected paper must be in the enrollment's authorized papers")
        return self


class Destination(Contract):
    course_id: UUID
    curriculum_id: UUID
    paper_id: UUID | None = None
    batch_id: UUID | None = None
    overview: bool = False
    mixed_papers: bool = False
    topic_ids: list[str] = Field(default_factory=list, max_length=500)
    material_type: Literal["notes", "textbook", "practice", "worked_examples"] = "notes"
    language: str = Field(default="English", min_length=1, max_length=80)

    @model_validator(mode="after")
    def explicit_paper_mode(self) -> Destination:
        if sum((self.paper_id is not None, self.overview, self.mixed_papers)) != 1:
            raise ValueError("Choose exactly one: a paper, course overview, or mixed papers")
        if self.paper_id is None and self.topic_ids:
            raise ValueError("Topic mappings require a specific paper")
        return self


class UploadCreate(Contract):
    idempotency_key: str = Field(min_length=1, max_length=128)
    destination: Destination
    title: str = Field(min_length=1, max_length=180)
    kind: Literal["file", "text"]
    object_key: str | None = Field(default=None, max_length=1000)
    content: str | None = Field(default=None, max_length=2_000_000)

    @model_validator(mode="after")
    def faithful_input(self) -> UploadCreate:
        if self.kind == "file" and (not self.object_key or self.content is not None):
            raise ValueError("A file requires its staged upload key, never caller-supplied extracted text")
        if self.kind == "text" and (not self.content or not self.content.strip() or self.object_key):
            raise ValueError("A text source requires nonempty text and no object key")
        return self


class AssignmentSave(Destination):
    source_version_id: UUID
    block_ids: list[str] = Field(min_length=1, max_length=20000)
    idempotency_key: str = Field(min_length=1, max_length=128)
    expected_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def concrete_assignment(self) -> AssignmentSave:
        if self.mixed_papers:
            raise ValueError("Split mixed material into explicit paper assignments before saving")
        if len(set(self.block_ids)) != len(self.block_ids):
            raise ValueError("Block IDs must be distinct")
        return self


class Approval(Contract):
    expected_revision: int = Field(ge=1)
    expected_source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=3, max_length=2000)
    mismatch_confirmed: bool = False


class IndexRequest(Contract):
    expected_revision: int = Field(ge=1)


class ReleaseCreate(Contract):
    course_id: UUID
    curriculum_id: UUID
    assignment_ids: list[UUID] = Field(min_length=1, max_length=500)
    artifact_ids: list[UUID] = Field(default_factory=list, max_length=500)


class PublishRequest(Contract):
    expected_epoch: int = Field(ge=0)


class Withdrawal(Contract):
    reason: str = Field(min_length=3, max_length=2000)


class PreviewRequest(Contract):
    enrollment_id: UUID
    query: str = Field(min_length=1, max_length=12000)
    selected_paper_id: UUID | None = None


class ArtifactGenerate(Contract):
    assignment_ids: list[UUID] = Field(min_length=1, max_length=20)
    artifact_type: Literal["summary", "flashcards", "practice_questions", "translation", "worked_example"]
    instructions: str = Field(default="", max_length=1000)


class ArtifactReview(Contract):
    expected_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=3, max_length=2000)
    answer_key_validated: bool = False


class AcademicReviewResolution(Contract):
    status: Literal["pending", "reviewed", "dismissed"]
