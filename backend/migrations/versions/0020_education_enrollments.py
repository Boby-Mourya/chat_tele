"""Add workspace-scoped Education enrollments.

Revision ID: 0020_education_enrollments
Revises: 0019_education_student_identities
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020_education_enrollments"
down_revision = "0019_education_student_identities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "education_enrollments" in tables:
        return

    op.create_table(
        "education_enrollments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("course_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=True),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('pending', 'active', 'suspended', 'expired', 'revoked', 'graduated')",
            name="ck_education_enrollments_status",
        ),
        sa.CheckConstraint(
            "ends_on IS NULL OR starts_on IS NULL OR ends_on >= starts_on",
            name="ck_education_enrollments_date_range",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["education_students.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["course_id"], ["education_courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["batch_id"], ["education_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "student_id",
            "course_id",
            "batch_id",
            "agent_id",
            name="uq_education_enrollments_assignment",
        ),
    )
    op.create_index("ix_education_enrollments_tenant_id", "education_enrollments", ["tenant_id"])
    op.create_index("ix_education_enrollments_workspace_id", "education_enrollments", ["workspace_id"])
    op.create_index("ix_education_enrollments_student_id", "education_enrollments", ["student_id"])
    op.create_index("ix_education_enrollments_course_id", "education_enrollments", ["course_id"])
    op.create_index("ix_education_enrollments_batch_id", "education_enrollments", ["batch_id"])
    op.create_index("ix_education_enrollments_agent_id", "education_enrollments", ["agent_id"])
    op.create_index(
        "ix_education_enrollments_scope",
        "education_enrollments",
        ["tenant_id", "workspace_id", "status"],
    )
    op.create_index(
        "ix_education_enrollments_student",
        "education_enrollments",
        ["workspace_id", "student_id", "status"],
    )
    op.create_index(
        "ix_education_enrollments_course_batch",
        "education_enrollments",
        ["workspace_id", "course_id", "batch_id", "status"],
    )
    op.create_index(
        "ix_education_enrollments_agent",
        "education_enrollments",
        ["workspace_id", "agent_id", "status"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "education_enrollments" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("education_enrollments")
