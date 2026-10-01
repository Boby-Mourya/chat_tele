"""Add safe durable channel delivery attempt history.

Revision ID: 0037_channel_delivery_attempts
Revises: 0036_channel_health_snapshots
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0037_channel_delivery_attempts"
down_revision = "0036_channel_health_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "channel_delivery_attempts" in tables:
        return

    op.create_table(
        "channel_delivery_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("delivery_id", sa.Uuid(), nullable=False),
        sa.Column("phase", sa.String(length=20), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(length=40), nullable=False),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["delivery_id"],
            ["channel_outbound_deliveries.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_channel_delivery_attempts_tenant_id",
        "channel_delivery_attempts",
        ["tenant_id"],
    )
    op.create_index(
        "ix_channel_delivery_attempts_workspace_id",
        "channel_delivery_attempts",
        ["workspace_id"],
    )
    op.create_index(
        "ix_channel_delivery_attempts_delivery_id",
        "channel_delivery_attempts",
        ["delivery_id"],
    )
    op.create_index(
        "ix_channel_delivery_attempts_created_at",
        "channel_delivery_attempts",
        ["created_at"],
    )
    op.create_index(
        "ix_channel_delivery_attempt_scope",
        "channel_delivery_attempts",
        ["tenant_id", "workspace_id", "delivery_id", "created_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "channel_delivery_attempts" in tables:
        op.drop_table("channel_delivery_attempts")
