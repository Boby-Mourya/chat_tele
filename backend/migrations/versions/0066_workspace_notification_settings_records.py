"""Add normalized workspace notification settings."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0066_workspace_notification_settings_records"
down_revision = "0065_workspace_developer_settings_records"
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "workspace_notification_settings_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("member_changes", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("security_alerts", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("billing_alerts", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("channel_failures", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("integration_failures", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("weekly_digest", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("recipients_json", JSON, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", name="uq_workspace_notification_settings_workspace"),
    )
    op.create_index(
        "ix_workspace_notification_settings_tenant_workspace",
        "workspace_notification_settings_records",
        ["tenant_id", "workspace_id"],
    )


def downgrade() -> None:
    op.drop_table("workspace_notification_settings_records")
