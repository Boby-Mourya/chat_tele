"""Durable receipts for authenticated CRM/LMS enrollment events."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base


class EducationEnrollmentEvent(Base):
    __tablename__ = "education_enrollment_events"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "agent_id", "source", "event_id", name="uq_education_enrollment_event"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(String(60))
    event_id: Mapped[str] = mapped_column(String(160))
    fingerprint: Mapped[str] = mapped_column(String(64))
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("education_students.id"))
    enrollment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("education_enrollments.id"))
    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leads.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
