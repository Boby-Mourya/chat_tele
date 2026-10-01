"""Durable delivery attempts for idempotent assignment/revision index stages."""
from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.course_knowledge_models import AgentBoundary
from northstar_api.database import Base


class CourseIndexDispatch(AgentBoundary, Base):
    __tablename__ = "course_knowledge_index_dispatch"
    assignment_id: Mapped[UUID] = mapped_column(ForeignKey("course_knowledge_assignments.id", ondelete="CASCADE"), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_dispatch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(200))


class CourseStudyReceipt(AgentBoundary, Base):
    """Durable menu response; a retry must not reinterpret a numeric selection."""
    __tablename__ = "course_knowledge_study_receipts"
    receipt_id: Mapped[UUID] = mapped_column(primary_key=True)
    identity_id: Mapped[UUID | None] = mapped_column(ForeignKey("education_student_identities.id", ondelete="SET NULL"))
    prompt: Mapped[str] = mapped_column(Text)
    scope_fingerprint: Mapped[str] = mapped_column(String(64))
    sent_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
