"""Add durable in-app notifications.

Revision ID: 0031_notifications
Revises: 0030_audit_extension
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0031_notifications"
down_revision = "0030_audit_extension"
branch_labels = None
depends_on = None

JSONType = sa.JSON().with_variant(JSONB, "postgresql")


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "notifications" not in tables:
        op.create_table(
            "notifications",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("workspace_id", sa.Uuid(), nullable=True),
            sa.Column("recipient_user_id", sa.Uuid(), nullable=False),
            sa.Column("category", sa.String(length=40), nullable=False, server_default="system"),
            sa.Column("severity", sa.String(length=20), nullable=False, server_default="info"),
            sa.Column("title", sa.String(length=180), nullable=False),
            sa.Column("body", sa.String(length=1000), nullable=False),
            sa.Column("action_url", sa.String(length=500), nullable=True),
            sa.Column("action_label", sa.String(length=120), nullable=True),
            sa.Column("dedupe_key", sa.String(length=220), nullable=False),
            sa.Column("source_event_id", sa.Uuid(), nullable=True),
            sa.Column("metadata_json", JSONType, nullable=False, server_default=sa.text("'{}'")),
            sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["recipient_user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "tenant_id",
                "recipient_user_id",
                "dedupe_key",
                name="uq_notifications_recipient_dedupe",
            ),
        )
        op.create_index("ix_notifications_tenant_id", "notifications", ["tenant_id"])
        op.create_index("ix_notifications_workspace_id", "notifications", ["workspace_id"])
        op.create_index("ix_notifications_recipient_user_id", "notifications", ["recipient_user_id"])
        op.create_index("ix_notifications_source_event_id", "notifications", ["source_event_id"])
        op.create_index("ix_notifications_read_at", "notifications", ["read_at"])
        op.create_index("ix_notifications_archived_at", "notifications", ["archived_at"])
        op.create_index(
            "ix_notifications_recipient_created",
            "notifications",
            ["tenant_id", "recipient_user_id", "created_at"],
        )
        op.create_index(
            "ix_notifications_unread",
            "notifications",
            ["tenant_id", "recipient_user_id", "read_at", "created_at"],
        )
        op.create_index(
            "ix_notifications_workspace",
            "notifications",
            ["tenant_id", "workspace_id", "recipient_user_id", "created_at"],
        )

    if bind.dialect.name == "postgresql":
        for role in ("northstar_app", "northstar_service"):
            op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "notifications" TO "{role}"')


def downgrade() -> None:
    bind = op.get_bind()
    if "notifications" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("notifications")
