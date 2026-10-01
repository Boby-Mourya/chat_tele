from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base


class BatchStatus(str, enum.Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class EducationBatch(Base):
    """A durable course batch scoped to one tenant workspace."""

    __tablename__ = "education_batches"
    __table_args__ = (
        UniqueConstraint("workspace_id", "code", name="uq_education_batches_workspace_code"),
        CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_education_batches_status",
        ),
        CheckConstraint(
            "ends_on IS NULL OR starts_on IS NULL OR ends_on >= starts_on",
            name="ck_education_batches_date_range",
        ),
        Index(
            "ix_education_batches_scope",
            "tenant_id",
            "workspace_id",
            "course_id",
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
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("education_courses.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    # Nullable only for backward compatibility with direct legacy fixtures. All
    # API-created batches are attached to a curriculum.
    curriculum_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("education_curricula.id", ondelete="RESTRICT"), index=True, nullable=True
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    starts_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    ends_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=BatchStatus.ACTIVE.value)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
