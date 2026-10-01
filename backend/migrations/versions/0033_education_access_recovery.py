from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0033_education_access_recovery"
down_revision = "0032_telegram_outbound"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    return name in inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if _table_exists("education_access_recovery_challenges"):
        return
    op.create_table(
        "education_access_recovery_challenges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("enrollment_id", sa.Uuid(), nullable=False),
        sa.Column("identity_type", sa.String(length=32), nullable=False),
        sa.Column("normalized_identifier", sa.String(length=320), nullable=False),
        sa.Column("delivery_email", sa.String(length=320), nullable=False),
        sa.Column("code_digest", sa.String(length=64), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "identity_type IN ('whatsapp', 'telegram', 'website_login', 'alternate_phone')",
            name="ck_education_access_recovery_identity_type",
        ),
        sa.CheckConstraint(
            "failed_attempts >= 0",
            name="ck_education_access_recovery_failed_attempts",
        ),
        sa.CheckConstraint("max_attempts > 0", name="ck_education_access_recovery_max_attempts"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["education_students.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["enrollment_id"], ["education_enrollments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_education_access_recovery_challenges_tenant_id",
        "education_access_recovery_challenges",
        ["tenant_id"],
    )
    op.create_index(
        "ix_education_access_recovery_challenges_workspace_id",
        "education_access_recovery_challenges",
        ["workspace_id"],
    )
    op.create_index(
        "ix_education_access_recovery_challenges_agent_id",
        "education_access_recovery_challenges",
        ["agent_id"],
    )
    op.create_index(
        "ix_education_access_recovery_challenges_student_id",
        "education_access_recovery_challenges",
        ["student_id"],
    )
    op.create_index(
        "ix_education_access_recovery_challenges_enrollment_id",
        "education_access_recovery_challenges",
        ["enrollment_id"],
    )
    op.create_index(
        "ix_education_access_recovery_scope",
        "education_access_recovery_challenges",
        ["tenant_id", "workspace_id", "agent_id", "expires_at"],
    )
    op.create_index(
        "ix_education_access_recovery_student",
        "education_access_recovery_challenges",
        ["workspace_id", "student_id", "consumed_at"],
    )


def downgrade() -> None:
    if _table_exists("education_access_recovery_challenges"):
        op.drop_table("education_access_recovery_challenges")
