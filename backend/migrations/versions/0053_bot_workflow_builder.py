"""Add purpose-scoped bot conversation workflows."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0053_bot_workflow_builder"
down_revision = "0052_structured_conversation_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bot_workflows",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("purpose", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("steps_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", name="uq_bot_workflows_agent"),
    )
    op.create_index("ix_bot_workflows_agent_id", "bot_workflows", ["agent_id"])
    op.create_index("ix_bot_workflows_tenant_id", "bot_workflows", ["tenant_id"])
    op.create_index("ix_bot_workflows_workspace_id", "bot_workflows", ["workspace_id"])
    op.create_index("ix_bot_workflows_scope", "bot_workflows", ["tenant_id", "workspace_id", "purpose", "status"])


def downgrade() -> None:
    op.drop_table("bot_workflows")
