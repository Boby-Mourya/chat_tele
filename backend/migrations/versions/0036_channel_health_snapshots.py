"""Add safe durable channel health history.

Revision ID: 0036_channel_health_snapshots
Revises: 0035_education_upsell_leads
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0036_channel_health_snapshots"
down_revision = "0035_education_upsell_leads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "channel_health_snapshots" in tables:
        return

    op.create_table(
        "channel_health_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connection_id"], ["channel_connections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_channel_health_snapshots_tenant_id",
        "channel_health_snapshots",
        ["tenant_id"],
    )
    op.create_index(
        "ix_channel_health_snapshots_connection_id",
        "channel_health_snapshots",
        ["connection_id"],
    )
    op.create_index(
        "ix_channel_health_snapshots_checked_at",
        "channel_health_snapshots",
        ["checked_at"],
    )
    op.create_index(
        "ix_channel_health_snapshots_connection_checked",
        "channel_health_snapshots",
        ["tenant_id", "connection_id", "checked_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "channel_health_snapshots" in tables:
        op.drop_table("channel_health_snapshots")
