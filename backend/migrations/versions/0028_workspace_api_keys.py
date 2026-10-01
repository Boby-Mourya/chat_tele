"""Add persistent workspace API keys.

Revision ID: 0028_workspace_api_keys
Revises: 0027_workspace_invitations
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0028_workspace_api_keys"
down_revision = "0027_workspace_invitations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "workspace_api_keys" in tables:
        return

    op.create_table(
        "workspace_api_keys",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("prefix", sa.String(length=24), nullable=False),
        sa.Column("secret_hash", sa.String(length=64), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("secret_hash", name="uq_workspace_api_keys_secret_hash"),
    )
    op.create_index("ix_workspace_api_keys_tenant_id", "workspace_api_keys", ["tenant_id"])
    op.create_index("ix_workspace_api_keys_workspace_id", "workspace_api_keys", ["workspace_id"])
    op.create_index("ix_workspace_api_keys_created_by", "workspace_api_keys", ["created_by_user_id"])
    op.create_index(
        "ix_workspace_api_keys_tenant_workspace_active",
        "workspace_api_keys",
        ["tenant_id", "workspace_id", "revoked_at"],
    )

    if bind.dialect.name == "postgresql":
        for role in ("northstar_app", "northstar_service"):
            op.execute(
                f'GRANT SELECT, INSERT, UPDATE, DELETE ON "workspace_api_keys" TO "{role}"'
            )


def downgrade() -> None:
    bind = op.get_bind()
    if "workspace_api_keys" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("workspace_api_keys")
