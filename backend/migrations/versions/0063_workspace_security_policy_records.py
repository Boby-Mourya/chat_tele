"""Add normalized workspace security policy records."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0063_workspace_security_policy_records"
down_revision = "0062_workspace_team_records"
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "workspace_security_policy_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("sensitive_data_masking", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("security_contact", sa.String(length=320), nullable=True),
        sa.Column("mfa_enforcement", sa.String(length=16), nullable=False, server_default="optional"),
        sa.Column("session_timeout_minutes", sa.Integer(), nullable=False, server_default="480"),
        sa.Column("password_min_length", sa.Integer(), nullable=False, server_default="12"),
        sa.Column("ip_allowlist_json", JSON, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("ip_denylist_json", JSON, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("trusted_domains_json", JSON, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("webhook_signing_required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("security_notifications", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", name="uq_workspace_security_policy_workspace"),
    )
    op.create_index(
        "ix_workspace_security_policy_tenant_workspace",
        "workspace_security_policy_records",
        ["tenant_id", "workspace_id"],
    )


def downgrade() -> None:
    op.drop_table("workspace_security_policy_records")
