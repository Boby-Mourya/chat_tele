"""Add workspace-scoped Education batches.

Revision ID: 0017_education_batches
Revises: 0016_education_courses
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017_education_batches"
down_revision = "0016_education_courses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "education_batches" in tables:
        return

    op.create_table(
        "education_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("course_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("starts_on", sa.Date(), nullable=True),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_education_batches_status",
        ),
        sa.CheckConstraint(
            "ends_on IS NULL OR starts_on IS NULL OR ends_on >= starts_on",
            name="ck_education_batches_date_range",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["course_id"], ["education_courses.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "code", name="uq_education_batches_workspace_code"),
    )
    op.create_index("ix_education_batches_tenant_id", "education_batches", ["tenant_id"])
    op.create_index("ix_education_batches_workspace_id", "education_batches", ["workspace_id"])
    op.create_index("ix_education_batches_course_id", "education_batches", ["course_id"])
    op.create_index(
        "ix_education_batches_scope",
        "education_batches",
        ["tenant_id", "workspace_id", "course_id", "status"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "education_batches" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("education_batches")
