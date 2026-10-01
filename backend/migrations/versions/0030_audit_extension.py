"""Extend integration audit into the platform audit trail.

Revision ID: 0030_audit_extension
Revises: 0029_tenant_subscriptions
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Connection

revision = "0030_audit_extension"
down_revision = "0029_tenant_subscriptions"
branch_labels = None
depends_on = None

JSONType = sa.JSON().with_variant(JSONB, "postgresql")


def _columns(bind: Connection) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns("integration_audit_events")}


def _indexes(bind: Connection) -> set[str]:
    return {index["name"] for index in sa.inspect(bind).get_indexes("integration_audit_events")}


def upgrade() -> None:
    bind = op.get_bind()
    if "integration_audit_events" not in set(sa.inspect(bind).get_table_names()):
        return

    columns = _columns(bind)
    additions = []
    if "workspace_id" not in columns:
        additions.append(sa.Column("workspace_id", sa.Uuid(), nullable=True))
    if "category" not in columns:
        additions.append(
            sa.Column("category", sa.String(length=40), nullable=False, server_default="integration")
        )
    if "severity" not in columns:
        additions.append(
            sa.Column("severity", sa.String(length=20), nullable=False, server_default="info")
        )
    if "outcome" not in columns:
        additions.append(
            sa.Column("outcome", sa.String(length=20), nullable=False, server_default="success")
        )
    if "metadata_json" not in columns:
        additions.append(
            sa.Column("metadata_json", JSONType, nullable=False, server_default=sa.text("'{}'"))
        )

    if additions:
        with op.batch_alter_table("integration_audit_events") as batch_op:
            for column in additions:
                batch_op.add_column(column)

    indexes = _indexes(bind)
    if "ix_integration_audit_workspace" not in indexes:
        op.create_index(
            "ix_integration_audit_workspace",
            "integration_audit_events",
            ["tenant_id", "workspace_id", "created_at"],
        )
    if "ix_integration_audit_category" not in indexes:
        op.create_index(
            "ix_integration_audit_category",
            "integration_audit_events",
            ["tenant_id", "category", "created_at"],
        )
    if "ix_integration_audit_severity" not in indexes:
        op.create_index(
            "ix_integration_audit_severity",
            "integration_audit_events",
            ["tenant_id", "severity", "created_at"],
        )
    if "ix_integration_audit_events_workspace_id" not in indexes:
        op.create_index(
            "ix_integration_audit_events_workspace_id",
            "integration_audit_events",
            ["workspace_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "integration_audit_events" not in set(sa.inspect(bind).get_table_names()):
        return

    indexes = _indexes(bind)
    for name in (
        "ix_integration_audit_events_workspace_id",
        "ix_integration_audit_severity",
        "ix_integration_audit_category",
        "ix_integration_audit_workspace",
    ):
        if name in indexes:
            op.drop_index(name, table_name="integration_audit_events")

    columns = _columns(bind)
    removable = [
        name
        for name in ("metadata_json", "outcome", "severity", "category", "workspace_id")
        if name in columns
    ]
    if removable:
        with op.batch_alter_table("integration_audit_events") as batch_op:
            for name in removable:
                batch_op.drop_column(name)
