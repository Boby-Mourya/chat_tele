"""Normalize workspace white-label persistence alongside compatibility JSON.

Revision ID: 0058_workspace_branding_tables
Revises: 0057_workspace_conversation_assignments
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0058_workspace_branding_tables"
down_revision = "0057_workspace_conversation_assignments"
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(JSONB(), "postgresql")


def _workspace_keys() -> list[sa.Column]:
    return [
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "workspace_brand",
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("draft_json", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("published_json", JSON, nullable=True),
        sa.Column("published_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_workspace_brand_tenant_workspace", "workspace_brand", ["tenant_id", "workspace_id"])

    op.create_table(
        "workspace_brand_asset",
        sa.Column("id", sa.Uuid(), primary_key=True),
        *_workspace_keys(),
        sa.Column("kind", sa.String(length=80), nullable=False),
        sa.Column("value", sa.Text(), nullable=False, server_default=""),
        sa.Column("metadata_json", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("workspace_id", "kind", name="uq_workspace_brand_asset_kind"),
    )
    op.create_index("ix_workspace_brand_asset_tenant_workspace", "workspace_brand_asset", ["tenant_id", "workspace_id"])

    op.create_table(
        "workspace_brand_theme",
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tokens_json", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("typography_json", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("appearance_json", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "workspace_brand_surface",
        sa.Column("id", sa.Uuid(), primary_key=True),
        *_workspace_keys(),
        sa.Column("surface", sa.String(length=80), nullable=False),
        sa.Column("config_json", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("workspace_id", "surface", name="uq_workspace_brand_surface"),
    )
    op.create_index("ix_workspace_brand_surface_tenant_workspace", "workspace_brand_surface", ["tenant_id", "workspace_id"])

    op.create_table(
        "workspace_brand_version",
        sa.Column("id", sa.Uuid(), primary_key=True),
        *_workspace_keys(),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("branding_json", JSON, nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("change_note", sa.String(length=500), nullable=False, server_default=""),
        sa.UniqueConstraint("workspace_id", "version", name="uq_workspace_brand_version"),
    )
    op.create_index("ix_workspace_brand_version_tenant_workspace", "workspace_brand_version", ["tenant_id", "workspace_id"])

    op.create_table(
        "workspace_custom_domain",
        sa.Column("id", sa.Uuid(), primary_key=True),
        *_workspace_keys(),
        sa.Column("hostname", sa.String(length=253), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="dns_pending"),
        sa.Column("verification_name", sa.String(length=320), nullable=False),
        sa.Column("verification_value", sa.String(length=512), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("hostname", name="uq_workspace_custom_domain_hostname"),
    )
    op.create_index("ix_workspace_custom_domain_tenant_workspace", "workspace_custom_domain", ["tenant_id", "workspace_id"])

    for table in ("workspace_dashboard_layout", "workspace_email_brand", "workspace_widget_brand"):
        op.create_table(
            table,
            sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("config_json", JSON, nullable=False, server_default=sa.text("'{}'")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index(f"ix_{table}_tenant_workspace", table, ["tenant_id", "workspace_id"])

    if op.get_bind().dialect.name == "postgresql":
        for table in (
            "workspace_brand",
            "workspace_brand_asset",
            "workspace_brand_theme",
            "workspace_brand_surface",
            "workspace_brand_version",
            "workspace_custom_domain",
            "workspace_dashboard_layout",
            "workspace_email_brand",
            "workspace_widget_brand",
        ):
            op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{table}" TO northstar_app')


def downgrade() -> None:
    for table in (
        "workspace_widget_brand",
        "workspace_email_brand",
        "workspace_dashboard_layout",
        "workspace_custom_domain",
        "workspace_brand_version",
        "workspace_brand_surface",
        "workspace_brand_theme",
        "workspace_brand_asset",
        "workspace_brand",
    ):
        op.drop_table(table)
