"""Add immutable Education authorization context to conversations.

Revision ID: 0021_education_conversation_context
Revises: 0020_education_enrollments
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021_education_conversation_context"
down_revision = "0020_education_enrollments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "education_conversation_contexts" in tables:
        return

    op.create_table(
        "education_conversation_contexts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("enrollment_id", sa.Uuid(), nullable=False),
        sa.Column("course_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["student_id"], ["education_students.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["enrollment_id"], ["education_enrollments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["course_id"], ["education_courses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["batch_id"], ["education_batches.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "conversation_id",
            name="uq_education_conversation_context_conversation",
        ),
    )
    op.create_index(
        "ix_education_conversation_contexts_tenant_id",
        "education_conversation_contexts",
        ["tenant_id"],
    )
    op.create_index(
        "ix_education_conversation_contexts_workspace_id",
        "education_conversation_contexts",
        ["workspace_id"],
    )
    op.create_index(
        "ix_education_conversation_contexts_conversation_id",
        "education_conversation_contexts",
        ["conversation_id"],
    )
    op.create_index(
        "ix_education_conversation_contexts_agent_id",
        "education_conversation_contexts",
        ["agent_id"],
    )
    op.create_index(
        "ix_education_conversation_contexts_student_id",
        "education_conversation_contexts",
        ["student_id"],
    )
    op.create_index(
        "ix_education_conversation_contexts_enrollment_id",
        "education_conversation_contexts",
        ["enrollment_id"],
    )
    op.create_index(
        "ix_education_conversation_contexts_course_id",
        "education_conversation_contexts",
        ["course_id"],
    )
    op.create_index(
        "ix_education_conversation_contexts_batch_id",
        "education_conversation_contexts",
        ["batch_id"],
    )
    op.create_index(
        "ix_education_conversation_context_scope",
        "education_conversation_contexts",
        ["tenant_id", "workspace_id", "agent_id", "student_id"],
    )
    op.create_index(
        "ix_education_conversation_context_enrollment",
        "education_conversation_contexts",
        ["workspace_id", "enrollment_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "education_conversation_contexts" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("education_conversation_contexts")
