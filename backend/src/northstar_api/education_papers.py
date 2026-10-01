from __future__ import annotations

import enum
import uuid
from datetime import datetime

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


class PaperStatus(str, enum.Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class EducationPaper(Base):
    """A paper, part, or subject inside one versioned curriculum."""

    __tablename__ = "education_papers"
    __table_args__ = (
        UniqueConstraint("curriculum_id", "code", name="uq_education_papers_curriculum_code"),
        CheckConstraint("status IN ('active', 'archived')", name="ck_education_papers_status"),
        CheckConstraint("sequence >= 0", name="ck_education_papers_sequence"),
        Index(
            "ix_education_papers_scope",
            "tenant_id",
            "workspace_id",
            "course_id",
            "curriculum_id",
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
        ForeignKey("education_courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    curriculum_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("education_curricula.id", ondelete="CASCADE"), index=True, nullable=False
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    aliases: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=PaperStatus.ACTIVE.value)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
