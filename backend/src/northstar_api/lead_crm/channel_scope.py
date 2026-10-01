from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base


class AgentChannelBinding(Base):
    """Authoritative channel assignment for one AI Agent."""

    __tablename__ = "agent_channel_bindings"
    __table_args__ = (
        UniqueConstraint("agent_id", name="uq_agent_channel_binding_agent"),
        Index("ix_agent_channel_binding_scope", "tenant_id", "workspace_id", "channel_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    channel_type: Mapped[str] = mapped_column(String(60), default="website", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class WorkspaceChannelConnection(Base):
    """Bind a generic channel connection to a workspace and, optionally, one Agent."""

    __tablename__ = "workspace_channel_connections"
    __table_args__ = (
        UniqueConstraint("connection_id", name="uq_workspace_channel_connection"),
        Index("ix_workspace_channel_connection_scope", "tenant_id", "workspace_id", "agent_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), index=True, nullable=True
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("channel_connections.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
