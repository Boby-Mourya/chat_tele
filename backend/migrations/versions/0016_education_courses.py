"""Add workspace-scoped Education courses.

Revision ID: 0016_education_courses
Revises: 0015_agent_purpose
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016_education_courses"
down_revision = "0015_agent_purpose"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "education_courses" in tables:
        return

    op.create_table(
        "education_courses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_education_courses_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "code", name="uq_education_courses_workspace_code"),
    )
    op.create_index("ix_education_courses_tenant_id", "education_courses", ["tenant_id"])
    op.create_index("ix_education_courses_workspace_id", "education_courses", ["workspace_id"])
    op.create_index(
        "ix_education_courses_scope",
        "education_courses",
        ["tenant_id", "workspace_id", "status"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "education_courses" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("education_courses")
