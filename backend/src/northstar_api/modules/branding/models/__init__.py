from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base

JSONType = JSON().with_variant(JSONB, "postgresql")


class WorkspaceBrand(Base):
    __tablename__ = "workspace_brand"
    __table_args__ = (Index("ix_workspace_brand_tenant_workspace", "tenant_id", "workspace_id"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    draft_json: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    published_json: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    published_version: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class WorkspaceBrandAsset(Base):
    __tablename__ = "workspace_brand_asset"
    __table_args__ = (
        UniqueConstraint("workspace_id", "kind", name="uq_workspace_brand_asset_kind"),
        Index("ix_workspace_brand_asset_tenant_workspace", "tenant_id", "workspace_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(80))
    value: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class WorkspaceBrandTheme(Base):
    __tablename__ = "workspace_brand_theme"
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    tokens_json: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    typography_json: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    appearance_json: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class WorkspaceBrandSurface(Base):
    __tablename__ = "workspace_brand_surface"
    __table_args__ = (
        UniqueConstraint("workspace_id", "surface", name="uq_workspace_brand_surface"),
        Index("ix_workspace_brand_surface_tenant_workspace", "tenant_id", "workspace_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    surface: Mapped[str] = mapped_column(String(80))
    config_json: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class WorkspaceBrandVersion(Base):
    __tablename__ = "workspace_brand_version"
    __table_args__ = (
        UniqueConstraint("workspace_id", "version", name="uq_workspace_brand_version"),
        Index("ix_workspace_brand_version_tenant_workspace", "tenant_id", "workspace_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    branding_json: Mapped[dict[str, Any]] = mapped_column(JSONType)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    change_note: Mapped[str] = mapped_column(String(500), default="")


class WorkspaceCustomDomain(Base):
    __tablename__ = "workspace_custom_domain"
    __table_args__ = (
        UniqueConstraint("hostname", name="uq_workspace_custom_domain_hostname"),
        Index("ix_workspace_custom_domain_tenant_workspace", "tenant_id", "workspace_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    hostname: Mapped[str] = mapped_column(String(253))
    status: Mapped[str] = mapped_column(String(40), default="dns_pending")
    verification_name: Mapped[str] = mapped_column(String(320))
    verification_value: Mapped[str] = mapped_column(String(512))
    failure_reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class WorkspaceDashboardLayout(Base):
    __tablename__ = "workspace_dashboard_layout"
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class WorkspaceEmailBrand(Base):
    __tablename__ = "workspace_email_brand"
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class WorkspaceWidgetBrand(Base):
    __tablename__ = "workspace_widget_brand"
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


__all__ = [
    "WorkspaceBrand",
    "WorkspaceBrandAsset",
    "WorkspaceBrandSurface",
    "WorkspaceBrandTheme",
    "WorkspaceBrandVersion",
    "WorkspaceCustomDomain",
    "WorkspaceDashboardLayout",
    "WorkspaceEmailBrand",
    "WorkspaceWidgetBrand",
]
