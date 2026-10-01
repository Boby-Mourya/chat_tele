from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base


class EducationAccessRequestStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"


class EducationAccessRequest(Base):
    """Human-review fallback for Education identity/access recovery."""

    __tablename__ = "education_access_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'denied')",
            name="ck_education_access_requests_status",
        ),
        CheckConstraint(
            "identity_type IN ('whatsapp', 'telegram', 'website_login', 'alternate_phone')",
            name="ck_education_access_requests_identity_type",
        ),
        Index(
            "ix_education_access_requests_scope",
            "tenant_id",
            "workspace_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_education_access_requests_identity",
            "workspace_id",
            "identity_type",
            "normalized_identifier",
            "status",
        ),
        Index(
            "ix_education_access_requests_student",
            "workspace_id",
            "student_id",
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
    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    student_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("education_students.id", ondelete="SET NULL"), index=True, nullable=True
    )
    enrollment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("education_enrollments.id", ondelete="SET NULL"), index=True, nullable=True
    )
    student_number: Mapped[str] = mapped_column(String(80), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    identity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    normalized_identifier: Mapped[str] = mapped_column(String(320), nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=EducationAccessRequestStatus.PENDING.value
    )
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
