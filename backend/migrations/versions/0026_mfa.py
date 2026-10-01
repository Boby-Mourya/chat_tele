"""Add MFA settings and recovery codes.

Revision ID: 0026_mfa
Revises: 0025_password_reset
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026_mfa"
down_revision = "0025_password_reset"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "mfa_settings" not in tables:
        op.create_table(
            "mfa_settings",
            sa.Column("user_id", sa.Uuid(), nullable=False),
            sa.Column("secret_ciphertext", sa.LargeBinary(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("last_counter", sa.Integer(), nullable=True),
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("user_id"),
        )
    if "mfa_recovery_codes" not in tables:
        op.create_table(
            "mfa_recovery_codes",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("user_id", sa.Uuid(), nullable=False),
            sa.Column("code_hash", sa.String(length=64), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("code_hash", name="uq_mfa_recovery_codes_code_hash"),
        )
        op.create_index("ix_mfa_recovery_codes_user_id", "mfa_recovery_codes", ["user_id"])
        op.create_index("ix_mfa_recovery_codes_code_hash", "mfa_recovery_codes", ["code_hash"])
        op.create_index(
            "ix_mfa_recovery_codes_user_unused",
            "mfa_recovery_codes",
            ["user_id", "used_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "mfa_recovery_codes" in tables:
        op.drop_table("mfa_recovery_codes")
    if "mfa_settings" in tables:
        op.drop_table("mfa_settings")
