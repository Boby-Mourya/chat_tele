from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base

JSONType = JSON().with_variant(JSONB, "postgresql")
MutableJSON = MutableDict.as_mutable(JSONType)


class IntegrationAuditEvent(Base):
    """Append-only tenant audit event.

    The historical name is retained because existing CRM/channel code already writes
    to this table. New SaaS events use the same durable store instead of creating a
    second audit subsystem.
    """

    __tablename__ = "integration_audit_events"
    __table_args__ = (
        Index("ix_integration_audit_scope", "tenant_id", "created_at"),
        Index("ix_integration_audit_entity", "tenant_id", "entity_type", "entity_id"),
        Index("ix_integration_audit_action", "tenant_id", "action", "created_at"),
        Index("ix_integration_audit_workspace", "tenant_id", "workspace_id", "created_at"),
        Index("ix_integration_audit_category", "tenant_id", "category", "created_at"),
        Index("ix_integration_audit_severity", "tenant_id", "severity", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    # Deliberately not a cascading FK: audit history must survive workspace archival/deletion.
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(160))
    entity_type: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(
        String(40), default="integration", server_default="integration"
    )
    severity: Mapped[str] = mapped_column(String(20), default="info", server_default="info")
    outcome: Mapped[str] = mapped_column(String(20), default="success", server_default="success")
    before_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)
    after_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        MutableJSON, default=dict, server_default=text("'{}'")
    )
    request_id: Mapped[str | None] = mapped_column(String(128), index=True)
    ip_address: Mapped[str | None] = mapped_column(String(80))
    user_agent: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
