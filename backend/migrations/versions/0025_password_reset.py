"""Add password reset tokens and credential-version state.

Revision ID: 0025_password_reset
Revises: 0024_email_verification
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0025_password_reset"
down_revision = "0024_email_verification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "password_credential_states" not in tables:
        op.create_table(
            "password_credential_states",
            sa.Column("user_id", sa.Uuid(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("user_id"),
        )
    if "password_reset_tokens" not in tables:
        op.create_table(
            "password_reset_tokens",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("user_id", sa.Uuid(), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("token_hash", name="uq_password_reset_tokens_token_hash"),
        )
        op.create_index(
            "ix_password_reset_tokens_user_id",
            "password_reset_tokens",
            ["user_id"],
        )
        op.create_index(
            "ix_password_reset_tokens_token_hash",
            "password_reset_tokens",
            ["token_hash"],
        )
        op.create_index(
            "ix_password_reset_tokens_user_active",
            "password_reset_tokens",
            ["user_id", "consumed_at", "expires_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "password_reset_tokens" in tables:
        op.drop_table("password_reset_tokens")
    if "password_credential_states" in tables:
        op.drop_table("password_credential_states")
