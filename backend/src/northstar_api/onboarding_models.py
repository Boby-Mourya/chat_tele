from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base
from northstar_api.models import MutableJSON, MutableListJSON, TimestampMixin


class OrganizationSetup(Base, TimestampMixin):
    __tablename__ = "organization_setups"
    __table_args__ = (
        CheckConstraint("revision >= 0", name="setup_revision_nonnegative"),
        CheckConstraint("branding_choice IN ('unseen', 'customize', 'keep_default', 'deferred')", name="setup_brand_choice"),
    )

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    profile_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)
    draft_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)
    profile_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    branding_choice: Mapped[str] = mapped_column(String(24), default="unseen")
    choice_actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    choice_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    catalog_grants: Mapped[list[str]] = mapped_column(MutableListJSON, default=list)
