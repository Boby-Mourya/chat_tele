from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base

JSONType = JSON().with_variant(JSONB, "postgresql")


class ProgressStatus(str, enum.Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    PRACTICED = "practiced"


class AcademicReviewStatus(str, enum.Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class EducationTutorContext(Base):
    """Persistent active selection for one student using one Education Agent."""

    __tablename__ = "education_tutor_contexts"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "agent_id", "student_id", name="uq_education_tutor_context_student_agent"
        ),
        CheckConstraint(
            "interaction_state IN ('awaiting_course_selection', 'awaiting_paper_selection', "
            "'awaiting_quiz_answer', 'ready_for_question')",
            name="ck_education_tutor_context_interaction_state",
        ),
        Index("ix_education_tutor_context_scope", "tenant_id", "workspace_id", "agent_id", "student_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("education_students.id", ondelete="CASCADE"), nullable=False
    )
    active_enrollment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("education_enrollments.id", ondelete="SET NULL"), nullable=True
    )
    active_paper_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("education_papers.id", ondelete="SET NULL"), nullable=True
    )
    pending_enrollment_ids: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    interaction_state: Mapped[str] = mapped_column(String(40), nullable=False, default="ready_for_question")
    pending_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    selection_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    preferred_language: Mapped[str | None] = mapped_column(String(80), nullable=True)
    selected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class EducationPaperProgress(Base):
    __tablename__ = "education_paper_progress"
    __table_args__ = (
        UniqueConstraint(
            "enrollment_id", "paper_id", name="uq_education_paper_progress_enrollment_paper"
        ),
        CheckConstraint(
            "status IN ('not_started', 'in_progress', 'practiced')",
            name="ck_education_paper_progress_status",
        ),
        Index("ix_education_paper_progress_student", "workspace_id", "student_id", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("education_students.id", ondelete="CASCADE"), nullable=False
    )
    enrollment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("education_enrollments.id", ondelete="CASCADE"), nullable=False
    )
    paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("education_papers.id", ondelete="CASCADE"), nullable=False
    )
    questions_asked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    practice_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    correct_objective_answers: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=ProgressStatus.NOT_STARTED.value)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class EducationPracticeAttempt(Base):
    __tablename__ = "education_practice_attempts"
    __table_args__ = (
        Index("ix_education_practice_attempt_scope", "workspace_id", "student_id", "paper_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("education_students.id", ondelete="CASCADE"), nullable=False
    )
    enrollment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("education_enrollments.id", ondelete="CASCADE"), nullable=False
    )
    paper_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("education_papers.id", ondelete="CASCADE"), nullable=False)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    student_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_correct: Mapped[bool | None] = mapped_column(nullable=True)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class EducationAcademicReview(Base):
    __tablename__ = "education_academic_reviews"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'resolved', 'dismissed')",
            name="ck_education_academic_reviews_status",
        ),
        UniqueConstraint("assistant_message_id", name="uq_education_academic_review_assistant_message"),
        Index("ix_education_academic_review_queue", "workspace_id", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("education_students.id", ondelete="CASCADE"), nullable=False
    )
    enrollment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("education_enrollments.id", ondelete="CASCADE"), nullable=False
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("education_courses.id", ondelete="RESTRICT"), nullable=False
    )
    curriculum_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("education_curricula.id", ondelete="SET NULL"), nullable=True
    )
    paper_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("education_papers.id", ondelete="SET NULL"), nullable=True
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    assistant_message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, nullable=False, default=list)
    confidence_reason: Mapped[str] = mapped_column(String(120), nullable=False)
    correction: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=AcademicReviewStatus.OPEN.value)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
