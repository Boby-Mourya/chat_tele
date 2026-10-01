"""Add real workspace invitations and invited agent access.

Revision ID: 0027_workspace_invitations
Revises: 0026_mfa
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0027_workspace_invitations"
down_revision = "0026_mfa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "workspace_invitations" not in tables:
        op.create_table(
            "workspace_invitations",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("workspace_id", sa.Uuid(), nullable=False),
            sa.Column("email", sa.String(length=320), nullable=False),
            sa.Column("role", sa.String(length=32), nullable=False, server_default="operator"),
            sa.Column("all_agents_access", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
            sa.Column("invited_by_user_id", sa.Uuid(), nullable=True),
            sa.Column("accepted_by_user_id", sa.Uuid(), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("privacy_accepted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("declined_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("delivery_attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_delivery_error", sa.String(length=500), nullable=True),
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
                ["invited_by_user_id"],
                ["users.id"],
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["accepted_by_user_id"],
                ["users.id"],
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "workspace_id",
                "email",
                name="uq_workspace_invitations_workspace_email",
            ),
            sa.UniqueConstraint(
                "token_hash",
                name="uq_workspace_invitations_token_hash",
            ),
        )
        op.create_index(
            "ix_workspace_invitations_tenant_id",
            "workspace_invitations",
            ["tenant_id"],
        )
        op.create_index(
            "ix_workspace_invitations_workspace_id",
            "workspace_invitations",
            ["workspace_id"],
        )
        op.create_index(
            "ix_workspace_invitations_invited_by_user_id",
            "workspace_invitations",
            ["invited_by_user_id"],
        )
        op.create_index(
            "ix_workspace_invitations_accepted_by_user_id",
            "workspace_invitations",
            ["accepted_by_user_id"],
        )
        op.create_index(
            "ix_workspace_invitations_tenant_workspace_status",
            "workspace_invitations",
            ["tenant_id", "workspace_id", "status"],
        )
        op.create_index(
            "ix_workspace_invitations_email",
            "workspace_invitations",
            ["email"],
        )
        op.create_index(
            "ix_workspace_invitations_expires_at",
            "workspace_invitations",
            ["expires_at"],
        )

    tables = set(sa.inspect(bind).get_table_names())
    if "workspace_invitation_agent_access" not in tables:
        op.create_table(
            "workspace_invitation_agent_access",
            sa.Column("invitation_id", sa.Uuid(), nullable=False),
            sa.Column("agent_id", sa.Uuid(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.ForeignKeyConstraint(
                ["invitation_id"],
                ["workspace_invitations.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("invitation_id", "agent_id"),
        )
        op.create_index(
            "ix_workspace_invitation_agent_access_agent",
            "workspace_invitation_agent_access",
            ["agent_id", "invitation_id"],
        )

    if bind.dialect.name == "postgresql":
        for role in ("northstar_app", "northstar_service"):
            op.execute(
                f'GRANT SELECT, INSERT, UPDATE, DELETE ON "workspace_invitations" TO "{role}"'
            )
            op.execute(
                f'GRANT SELECT, INSERT, UPDATE, DELETE ON '
                f'"workspace_invitation_agent_access" TO "{role}"'
            )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "workspace_invitation_agent_access" in tables:
        op.drop_table("workspace_invitation_agent_access")
    if "workspace_invitations" in tables:
        op.drop_table("workspace_invitations")
