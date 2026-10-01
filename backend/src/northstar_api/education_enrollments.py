from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base


class EnrollmentStatus(str, enum.Enum):
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    EXPIRED = "expired"
    REVOKED = "revoked"
    GRADUATED = "graduated"


class EducationEnrollment(Base):
    """A durable Student → Course → Batch → Education Agent access assignment."""

    __tablename__ = "education_enrollments"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "student_id",
            "course_id",
            "batch_id",
            "agent_id",
            name="uq_education_enrollments_assignment",
        ),
        CheckConstraint(
            "status IN ('pending', 'active', 'suspended', 'expired', 'revoked', 'graduated')",
            name="ck_education_enrollments_status",
        ),
        CheckConstraint(
            "ends_on IS NULL OR starts_on IS NULL OR ends_on >= starts_on",
            name="ck_education_enrollments_date_range",
        ),
        Index(
            "ix_education_enrollments_scope",
            "tenant_id",
            "workspace_id",
            "status",
        ),
        Index(
            "ix_education_enrollments_student",
            "workspace_id",
            "student_id",
            "status",
        ),
        Index(
            "ix_education_enrollments_course_batch",
            "workspace_id",
            "course_id",
            "batch_id",
            "status",
        ),
        Index(
            "ix_education_enrollments_agent",
            "workspace_id",
            "agent_id",
            "status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("education_students.id", ondelete="CASCADE"), index=True, nullable=False
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("education_courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    curriculum_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("education_curricula.id", ondelete="RESTRICT"), index=True, nullable=True
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("education_batches.id", ondelete="CASCADE"), index=True, nullable=False
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    all_papers: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    paper_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    authorization_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    starts_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    ends_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=EnrollmentStatus.PENDING.value)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
