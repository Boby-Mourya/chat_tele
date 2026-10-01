"""Add self-service email verification state and token storage.

Revision ID: 0024_email_verification
Revises: 0023_purpose_aware_resolution
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024_email_verification"
down_revision = "0023_purpose_aware_resolution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "email_verification_states" not in tables:
        op.create_table(
            "email_verification_states",
            sa.Column("user_id", sa.Uuid(), nullable=False),
            sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("user_id"),
        )
    if "email_verification_tokens" not in tables:
        op.create_table(
            "email_verification_tokens",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("user_id", sa.Uuid(), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("token_hash", name="uq_email_verification_tokens_token_hash"),
        )
        op.create_index(
            "ix_email_verification_tokens_user_id",
            "email_verification_tokens",
            ["user_id"],
        )
        op.create_index(
            "ix_email_verification_tokens_token_hash",
            "email_verification_tokens",
            ["token_hash"],
        )
        op.create_index(
            "ix_email_verification_tokens_user_active",
            "email_verification_tokens",
            ["user_id", "consumed_at", "expires_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "email_verification_tokens" in tables:
        op.drop_table("email_verification_tokens")
    if "email_verification_states" in tables:
        op.drop_table("email_verification_states")
