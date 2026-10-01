from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base


class WorkspaceCRMConnection(Base):
    """Assign an existing CRM connection to exactly one operational workspace.

    The legacy CRM connection table stays intact for provider compatibility while
    this relation becomes the workspace authorization boundary.
    """

    __tablename__ = "workspace_crm_connections"
    __table_args__ = (
        UniqueConstraint("connection_id", name="uq_workspace_crm_connection"),
        UniqueConstraint("workspace_id", "connection_id", name="uq_workspace_crm_connection_scope"),
        Index("ix_workspace_crm_connections_scope", "tenant_id", "workspace_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("crm_connections.id", ondelete="CASCADE"), index=True
    )
    auto_sync_new_leads: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    auto_sync_updates: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class WorkspaceCRMRoute(Base):
    """Assign a legacy CRM route to one workspace."""

    __tablename__ = "workspace_crm_routes"
    __table_args__ = (
        UniqueConstraint("route_id", name="uq_workspace_crm_route"),
        UniqueConstraint("workspace_id", "route_id", name="uq_workspace_crm_route_scope"),
        Index("ix_workspace_crm_routes_scope", "tenant_id", "workspace_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    route_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crm_routes.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
