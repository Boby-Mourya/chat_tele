"""Durable, scoped receipts for explicit copies of approved starter material."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base


class StarterTemplateClone(Base):
    __tablename__ = "starter_template_clones"
    __table_args__ = (
        UniqueConstraint("tenant_id", "workspace_id", "actor_id", "request_id", name="uq_starter_clone_request"),
        CheckConstraint("catalog_version >= 1", name="starter_clone_catalog_version"),
        Index("ix_starter_clones_scope", "tenant_id", "workspace_id", "created_at"),
    )

    # A request ID is unique only within an authenticated actor/workspace scope.
    id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    request_id: Mapped[UUID] = mapped_column()
    catalog_id: Mapped[str] = mapped_column(String(100))
    catalog_version: Mapped[int] = mapped_column(Integer)
    fingerprint: Mapped[str] = mapped_column(String(64))
    recipe_digest: Mapped[str] = mapped_column(String(64))
    agent_id: Mapped[UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
