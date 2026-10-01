"""Add normalized workspace team records alongside the settings projection."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0062_workspace_team_records"
down_revision = "0061_platform_admin_assignments"
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "workspace_team_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("member_ids_json", JSON, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("manager_ids_json", JSON, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("role_ids_json", JSON, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("queue_ids_json", JSON, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("agent_ids_json", JSON, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("channel_ids_json", JSON, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("business_hours_json", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("escalation_rule", sa.String(length=1000), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "name", name="uq_workspace_team_records_name"),
    )
    op.create_index(
        "ix_workspace_team_records_tenant_workspace",
        "workspace_team_records",
        ["tenant_id", "workspace_id"],
    )


def downgrade() -> None:
    op.drop_table("workspace_team_records")
