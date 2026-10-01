"""Add encrypted workspace-scoped LLM provider connections."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0058_llm_connections"
down_revision = "0057_workspace_conversation_assignments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("endpoint_url", sa.String(length=500), nullable=False),
        sa.Column("credentials_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="configured"),
        sa.Column(
            "metadata_json",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "name", name="uq_llm_connections_workspace_name"),
    )
    op.create_index("ix_llm_connections_tenant_id", "llm_connections", ["tenant_id"])
    op.create_index("ix_llm_connections_workspace_id", "llm_connections", ["workspace_id"])
    op.create_index("ix_llm_connections_scope", "llm_connections", ["tenant_id", "workspace_id", "provider"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute('GRANT SELECT, INSERT, UPDATE, DELETE ON "llm_connections" TO northstar_app')


def downgrade() -> None:
    op.drop_table("llm_connections")
