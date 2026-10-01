from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from northstar_api.schemas import APIModel


class PracticeCreate(APIModel):
    agent_id: UUID
    student_id: UUID
    enrollment_id: UUID
    paper_id: UUID
    idempotency_key: str = Field(min_length=1, max_length=128)
    question: str = Field(min_length=1)
    answer_key: str = Field(min_length=1)
    conversation_id: UUID | None = None


class PracticeSubmit(APIModel):
    student_answer: str = Field(min_length=1)


class PracticeOut(APIModel):
    id: UUID
    agent_id: UUID
    student_id: UUID
    enrollment_id: UUID
    paper_id: UUID
    conversation_id: UUID | None
    question: str
    student_answer: str | None
    is_correct: bool | None
    feedback: str | None
    status: Literal["open", "answered"]
    created_at: datetime
    updated_at: datetime


class ProgressOut(APIModel):
    id: UUID
    agent_id: UUID
    student_id: UUID
    enrollment_id: UUID
    paper_id: UUID
    questions_asked: int
    practice_attempts: int
    objective_answers_correct: int
    objective_answers_graded: int
    learning_status: Literal["not_started", "practicing", "review_needed"]
    last_activity_at: datetime | None


class ReviewAssign(APIModel):
    reviewer_id: UUID


class ReviewResolve(APIModel):
    outcome: Literal["corrected", "confirmed"]
    resolution: str = Field(min_length=1)
    request_correction_delivery: bool = False


class ReviewOut(APIModel):
    id: UUID
    agent_id: UUID
    student_id: UUID | None
    enrollment_id: UUID
    course_id: UUID | None
    curriculum_id: UUID | None
    paper_id: UUID | None
    batch_id: UUID | None
    message_id: UUID
    question: str
    answer: str
    reason: str
    internal_evidence: list[dict[str, Any]]
    external_evidence: list[dict[str, Any]]
    status: str
    assigned_reviewer: UUID | None
    resolution: str | None
    correction_delivery_status: str
    created_at: datetime
    updated_at: datetime


class TutorContextOut(APIModel):
    identity_id: UUID
    agent_id: UUID
    enrollment_id: UUID | None
    interaction_state: str
    menu_id: UUID | None
    menu_options: list[str]
    menu_created_at: datetime | None
    menu_expires_at: datetime | None
    selection_revision: int
    pending_question: str | None


class AnswerExplanation(APIModel):
    message_id: UUID
    enrollment_id: UUID
    context_fingerprint: str
    retrieved_sources: list[dict[str, Any]]
    fallback_reason: str | None
    academic_review_id: UUID | None
    academic_review_status: str | None
