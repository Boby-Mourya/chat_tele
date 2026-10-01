"""Make resolved-conversation lead finalization idempotent.

Revision ID: 0012_conversation_resolution_leads
Revises: 0011_tenant_workspaces
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012_conversation_resolution_leads"
down_revision = "0011_tenant_workspaces"
branch_labels = None
depends_on = None

LEAD_CONVERSATION_INDEX = "uq_leads_workspace_conversation"


def _indexes(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table) if item.get("name")}


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "workspaces" in tables:
        # Asia/Calcutta remains an IANA alias, but Asia/Kolkata is the canonical
        # name used by the product and new workspace forms.
        op.execute(
            sa.text(
                "UPDATE workspaces SET timezone = 'Asia/Kolkata' "
                "WHERE timezone = 'Asia/Calcutta'"
            )
        )
        with op.batch_alter_table("workspaces") as batch:
            batch.alter_column(
                "timezone",
                existing_type=sa.String(length=80),
                server_default="Asia/Kolkata",
                existing_nullable=False,
            )

    if "leads" in tables and LEAD_CONVERSATION_INDEX not in _indexes("leads"):
        columns = {item["name"] for item in sa.inspect(bind).get_columns("leads")}
        if {"workspace_id", "conversation_id"} <= columns:
            # PostgreSQL and SQLite both allow multiple NULL values in a unique
            # index, so manual/API leads without a conversation remain valid.
            op.create_index(
                LEAD_CONVERSATION_INDEX,
                "leads",
                ["workspace_id", "conversation_id"],
                unique=True,
            )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "leads" in tables and LEAD_CONVERSATION_INDEX in _indexes("leads"):
        op.drop_index(LEAD_CONVERSATION_INDEX, table_name="leads")
    if "workspaces" in tables:
        op.execute(
            sa.text(
                "UPDATE workspaces SET timezone = 'Asia/Calcutta' "
                "WHERE timezone = 'Asia/Kolkata'"
            )
        )
        with op.batch_alter_table("workspaces") as batch:
            batch.alter_column(
                "timezone",
                existing_type=sa.String(length=80),
                server_default="Asia/Calcutta",
                existing_nullable=False,
            )
