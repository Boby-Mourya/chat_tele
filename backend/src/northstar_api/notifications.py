from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base

JSONType = JSON().with_variant(JSONB, "postgresql")
MutableJSON = MutableDict.as_mutable(JSONType)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "recipient_user_id",
            "dedupe_key",
            name="uq_notifications_recipient_dedupe",
        ),
        Index(
            "ix_notifications_recipient_created",
            "tenant_id",
            "recipient_user_id",
            "created_at",
        ),
        Index(
            "ix_notifications_unread",
            "tenant_id",
            "recipient_user_id",
            "read_at",
            "created_at",
        ),
        Index(
            "ix_notifications_workspace",
            "tenant_id",
            "workspace_id",
            "recipient_user_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    # Keep the identifier for historical context without cascading notification
    # history when a Workspace is archived or removed.
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    recipient_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    category: Mapped[str] = mapped_column(String(40), default="system", server_default="system")
    severity: Mapped[str] = mapped_column(String(20), default="info", server_default="info")
    title: Mapped[str] = mapped_column(String(180))
    body: Mapped[str] = mapped_column(String(1000))
    action_url: Mapped[str | None] = mapped_column(String(500))
    action_label: Mapped[str | None] = mapped_column(String(120))
    dedupe_key: Mapped[str] = mapped_column(String(220))
    source_event_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        MutableJSON,
        default=dict,
        server_default=text("'{}'"),
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
