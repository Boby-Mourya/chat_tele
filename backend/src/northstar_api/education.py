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
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base

JSONType = JSON().with_variant(JSONB, "postgresql")


class CourseStatus(str, enum.Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class EducationCourse(Base):
    """A durable course catalog entry scoped to one tenant workspace."""

    __tablename__ = "education_courses"
    __table_args__ = (
        UniqueConstraint("workspace_id", "code", name="uq_education_courses_workspace_code"),
        CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_education_courses_status",
        ),
        Index(
            "ix_education_courses_scope",
            "tenant_id",
            "workspace_id",
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
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    awarding_body: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    jurisdiction: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    aliases: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=CourseStatus.ACTIVE.value)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
