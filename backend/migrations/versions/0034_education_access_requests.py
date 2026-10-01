from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0034_education_access_requests"
down_revision = "0033_education_access_recovery"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    return name in inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if _table_exists("education_access_requests"):
        return
    op.create_table(
        "education_access_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=True),
        sa.Column("enrollment_id", sa.Uuid(), nullable=True),
        sa.Column("student_number", sa.String(length=80), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("identity_type", sa.String(length=32), nullable=False),
        sa.Column("normalized_identifier", sa.String(length=320), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("reviewed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'denied')",
            name="ck_education_access_requests_status",
        ),
        sa.CheckConstraint(
            "identity_type IN ('whatsapp', 'telegram', 'website_login', 'alternate_phone')",
            name="ck_education_access_requests_identity_type",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["education_students.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["enrollment_id"], ["education_enrollments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_education_access_requests_tenant_id",
        "education_access_requests",
        ["tenant_id"],
    )
    op.create_index(
        "ix_education_access_requests_workspace_id",
        "education_access_requests",
        ["workspace_id"],
    )
    op.create_index(
        "ix_education_access_requests_agent_id",
        "education_access_requests",
        ["agent_id"],
    )
    op.create_index(
        "ix_education_access_requests_student_id",
        "education_access_requests",
        ["student_id"],
    )
    op.create_index(
        "ix_education_access_requests_enrollment_id",
        "education_access_requests",
        ["enrollment_id"],
    )
    op.create_index(
        "ix_education_access_requests_scope",
        "education_access_requests",
        ["tenant_id", "workspace_id", "status", "created_at"],
    )
    op.create_index(
        "ix_education_access_requests_identity",
        "education_access_requests",
        ["workspace_id", "identity_type", "normalized_identifier", "status"],
    )
    op.create_index(
        "ix_education_access_requests_student",
        "education_access_requests",
        ["workspace_id", "student_id", "status"],
    )


def downgrade() -> None:
    if _table_exists("education_access_requests"):
        op.drop_table("education_access_requests")
