"""Add workspace-scoped Education students.

Revision ID: 0018_education_students
Revises: 0017_education_batches
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018_education_students"
down_revision = "0017_education_batches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "education_students" in tables:
        return

    op.create_table(
        "education_students",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("student_number", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("custom_fields", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_education_students_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "student_number",
            name="uq_education_students_workspace_student_number",
        ),
    )
    op.create_index("ix_education_students_tenant_id", "education_students", ["tenant_id"])
    op.create_index("ix_education_students_workspace_id", "education_students", ["workspace_id"])
    op.create_index("ix_education_students_email", "education_students", ["email"])
    op.create_index(
        "ix_education_students_scope",
        "education_students",
        ["tenant_id", "workspace_id", "status"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "education_students" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("education_students")
