from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base


class StudentIdentityType(str, enum.Enum):
    WHATSAPP = "whatsapp"
    TELEGRAM = "telegram"
    WEBSITE_LOGIN = "website_login"
    ALTERNATE_PHONE = "alternate_phone"


class StudentIdentityStatus(str, enum.Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    REVOKED = "revoked"


class EducationStudentIdentity(Base):
    """A normalized external identity linked to one workspace-scoped student profile."""

    __tablename__ = "education_student_identities"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "identity_type",
            "normalized_identifier",
            name="uq_education_student_identities_workspace_identity",
        ),
        CheckConstraint(
            "identity_type IN ('whatsapp', 'telegram', 'website_login', 'alternate_phone')",
            name="ck_education_student_identities_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'verified', 'revoked')",
            name="ck_education_student_identities_status",
        ),
        Index(
            "ix_education_student_identities_scope",
            "tenant_id",
            "workspace_id",
            "identity_type",
            "status",
        ),
        Index(
            "ix_education_student_identities_student",
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
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("education_students.id", ondelete="CASCADE"), index=True, nullable=False
    )
    identity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    identifier: Mapped[str] = mapped_column(String(320), nullable=False)
    normalized_identifier: Mapped[str] = mapped_column(String(320), nullable=False)
    label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=StudentIdentityStatus.PENDING.value
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
