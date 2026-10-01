from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, UniqueConstraint, false, func
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base


class EducationConversationContext(Base):
    """Authorization scope and Education-specific runtime state for one conversation."""

    __tablename__ = "education_conversation_contexts"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            name="uq_education_conversation_context_conversation",
        ),
        Index(
            "ix_education_conversation_context_scope",
            "tenant_id",
            "workspace_id",
            "agent_id",
            "student_id",
        ),
        Index(
            "ix_education_conversation_context_enrollment",
            "workspace_id",
            "enrollment_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("education_students.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    enrollment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("education_enrollments.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("education_courses.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    curriculum_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("education_curricula.id", ondelete="RESTRICT"), index=True, nullable=True
    )
    paper_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("education_papers.id", ondelete="RESTRICT"), index=True, nullable=True
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("education_batches.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    sales_intent_detected: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
