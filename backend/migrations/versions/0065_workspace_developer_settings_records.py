"""Add normalized workspace developer and webhook settings."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0065_workspace_developer_settings_records"
down_revision = "0064_workspace_team_logical_ids"
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "workspace_developer_settings_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("sandbox_mode", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("webhook_signing_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("webhook_events_json", JSON, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("rate_limit_per_minute", sa.Integer(), nullable=False, server_default="120"),
        sa.Column("request_log_retention_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("webhook_retry_limit", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", name="uq_workspace_developer_settings_workspace"),
    )
    op.create_index(
        "ix_workspace_developer_settings_tenant_workspace",
        "workspace_developer_settings_records",
        ["tenant_id", "workspace_id"],
    )


def downgrade() -> None:
    op.drop_table("workspace_developer_settings_records")
