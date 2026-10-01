"""Add durable Education student activity for purpose-aware resolution.

Revision ID: 0023_purpose_aware_resolution
Revises: 0022_education_knowledge_scope
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023_purpose_aware_resolution"
down_revision = "0022_education_knowledge_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "education_student_activity_events" in set(sa.inspect(bind).get_table_names()):
        return

    op.create_table(
        "education_student_activity_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("enrollment_id", sa.Uuid(), nullable=False),
        sa.Column("course_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolution", sa.String(length=120), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["education_students.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["enrollment_id"], ["education_enrollments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["course_id"], ["education_courses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["batch_id"], ["education_batches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "conversation_id",
            "event_type",
            "resolved_at",
            name="uq_education_student_activity_resolution_cycle",
        ),
    )
    for column in (
        "tenant_id",
        "workspace_id",
        "student_id",
        "enrollment_id",
        "course_id",
        "batch_id",
        "agent_id",
        "conversation_id",
    ):
        op.create_index(
            f"ix_education_student_activity_events_{column}",
            "education_student_activity_events",
            [column],
        )
    op.create_index(
        "ix_education_student_activity_scope",
        "education_student_activity_events",
        ["tenant_id", "workspace_id", "student_id", "created_at"],
    )
    op.create_index(
        "ix_education_student_activity_enrollment",
        "education_student_activity_events",
        ["workspace_id", "enrollment_id", "created_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "education_student_activity_events" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("education_student_activity_events")
