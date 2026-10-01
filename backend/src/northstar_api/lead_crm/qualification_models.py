from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base

JSONType = JSON().with_variant(JSONB, "postgresql")
MutableJSON = MutableDict.as_mutable(JSONType)


class LeadQualificationRule(Base):
    __tablename__ = "lead_qualification_rules"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_lead_qualification_rule_name"),
        Index("ix_lead_qualification_rules_active", "tenant_id", "enabled", "priority"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    version: Mapped[int] = mapped_column(Integer, default=1)
    conditions_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)
    actions_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
