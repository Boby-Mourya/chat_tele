from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base


class EducationAccessRecoveryChallenge(Base):
    """One-time proof challenge used to link a verified Student identity safely."""

    __tablename__ = "education_access_recovery_challenges"
    __table_args__ = (
        CheckConstraint(
            "identity_type IN ('whatsapp', 'telegram', 'website_login', 'alternate_phone')",
            name="ck_education_access_recovery_identity_type",
        ),
        CheckConstraint("failed_attempts >= 0", name="ck_education_access_recovery_failed_attempts"),
        CheckConstraint("max_attempts > 0", name="ck_education_access_recovery_max_attempts"),
        Index(
            "ix_education_access_recovery_scope",
            "tenant_id",
            "workspace_id",
            "agent_id",
            "expires_at",
        ),
        Index(
            "ix_education_access_recovery_student",
            "workspace_id",
            "student_id",
            "consumed_at",
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
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("education_students.id", ondelete="CASCADE"), index=True, nullable=False
    )
    enrollment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("education_enrollments.id", ondelete="CASCADE"), index=True, nullable=False
    )
    identity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    normalized_identifier: Mapped[str] = mapped_column(String(320), nullable=False)
    delivery_email: Mapped[str] = mapped_column(String(320), nullable=False)
    code_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
