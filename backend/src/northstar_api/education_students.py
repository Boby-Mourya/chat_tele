from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base

JSONType = JSON().with_variant(JSONB, "postgresql")


class StudentStatus(str, enum.Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class EducationStudent(Base):
    """A durable student profile scoped to one tenant workspace."""

    __tablename__ = "education_students"
    __table_args__ = (
        UniqueConstraint("workspace_id", "telegram_phone_number", name="uq_student_telegram_phone"),
        UniqueConstraint(
            "workspace_id",
            "student_number",
            name="uq_education_students_workspace_student_number",
        ),
        CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_education_students_status",
        ),
        Index(
            "ix_education_students_scope",
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
    telegram_phone_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    telegram_phone_number: Mapped[str | None] = mapped_column(String(16), nullable=True)
    student_number: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    preferred_language: Mapped[str] = mapped_column(String(80), nullable=False, default="English")
    custom_fields: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=StudentStatus.ACTIVE.value)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
