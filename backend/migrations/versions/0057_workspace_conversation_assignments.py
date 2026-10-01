"""Add workspace-scoped conversation assignments.

Revision ID: 0057_workspace_conversation_assignments
Revises: 0056_workspace_api_key_scopes
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0057_workspace_conversation_assignments"
down_revision = "0056_workspace_api_key_scopes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_conversation_assignments",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("assigned_user_id", sa.Uuid(), nullable=True),
        sa.Column("assigned_team_id", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assigned_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("conversation_id"),
    )
    op.create_index(
        "ix_workspace_conversation_assignments_tenant_id",
        "workspace_conversation_assignments",
        ["tenant_id"],
    )
    op.create_index(
        "ix_workspace_conversation_assignments_workspace_id",
        "workspace_conversation_assignments",
        ["workspace_id"],
    )
    op.create_index(
        "ix_workspace_conversation_assignments_assigned_user_id",
        "workspace_conversation_assignments",
        ["assigned_user_id"],
    )
    op.create_index(
        "ix_workspace_conversation_assignments_assigned_team_id",
        "workspace_conversation_assignments",
        ["assigned_team_id"],
    )
    op.create_index(
        "ix_workspace_conversation_assignment_scope",
        "workspace_conversation_assignments",
        ["tenant_id", "workspace_id", "assigned_user_id"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            'GRANT SELECT, INSERT, UPDATE, DELETE ON "workspace_conversation_assignments" TO northstar_app'
        )


def downgrade() -> None:
    op.drop_table("workspace_conversation_assignments")
