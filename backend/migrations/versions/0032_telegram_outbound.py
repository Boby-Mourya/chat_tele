from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0032_telegram_outbound"
down_revision = "0031_notifications"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    return name in inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if not _table_exists("channel_outbound_deliveries"):
        op.create_table(
            "channel_outbound_deliveries",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("workspace_id", sa.Uuid(), nullable=False),
            sa.Column("connection_id", sa.Uuid(), nullable=True),
            sa.Column("message_id", sa.Uuid(), nullable=False),
            sa.Column("provider", sa.String(length=60), nullable=False),
            sa.Column("recipient_external_id", sa.String(length=180), nullable=False),
            sa.Column("status", sa.String(length=40), nullable=False, server_default="queued"),
            sa.Column("provider_message_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("dispatch_attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("next_dispatch_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error", sa.String(length=1000), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["connection_id"], ["channel_connections.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("provider", "message_id", name="uq_channel_outbound_provider_message"),
        )
        op.create_index(
            "ix_channel_outbound_tenant_provider_status",
            "channel_outbound_deliveries",
            ["tenant_id", "provider", "status", "next_dispatch_at"],
        )
        op.create_index(
            "ix_channel_outbound_connection_status",
            "channel_outbound_deliveries",
            ["connection_id", "status"],
        )
        op.create_index(
            "ix_channel_outbound_deliveries_tenant_id",
            "channel_outbound_deliveries",
            ["tenant_id"],
        )
        op.create_index(
            "ix_channel_outbound_deliveries_workspace_id",
            "channel_outbound_deliveries",
            ["workspace_id"],
        )
        op.create_index(
            "ix_channel_outbound_deliveries_connection_id",
            "channel_outbound_deliveries",
            ["connection_id"],
        )
        op.create_index(
            "ix_channel_outbound_deliveries_message_id",
            "channel_outbound_deliveries",
            ["message_id"],
        )

    if op.get_bind().dialect.name == "postgresql":
        op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON channel_outbound_deliveries TO northstar_app")
        op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON channel_outbound_deliveries TO northstar_service")


def downgrade() -> None:
    if _table_exists("channel_outbound_deliveries"):
        op.drop_table("channel_outbound_deliveries")
