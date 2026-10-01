"""Complete durable tutor menus, practice, progress, and academic review workflows."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0051_complete_education_tutor_workflows"
down_revision = "0050_merge_course_education_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("course_knowledge_study_selections") as batch:
        batch.add_column(
            sa.Column("interaction_state", sa.String(40), nullable=False, server_default="ready_for_question")
        )
        batch.add_column(sa.Column("pending_question", sa.Text(), nullable=True))
        batch.add_column(sa.Column("menu_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("menu_created_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("menu_expires_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("selection_revision", sa.Integer(), nullable=False, server_default="0"))
        batch.create_check_constraint(
            "ck_ck_selection_interaction_state",
            "interaction_state IN ('awaiting_course_selection', 'awaiting_paper_selection', "
            "'awaiting_quiz_answer', 'ready_for_question')",
        )
        batch.create_check_constraint("ck_ck_selection_revision", "selection_revision >= 0")

    with op.batch_alter_table("course_knowledge_academic_reviews") as batch:
        batch.add_column(sa.Column("student_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("course_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("curriculum_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("paper_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("batch_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("answer", sa.Text(), nullable=False, server_default=""))
        batch.add_column(
            sa.Column("internal_evidence", sa.JSON(), nullable=False, server_default=sa.text("'[]'"))
        )
        batch.add_column(
            sa.Column("external_evidence", sa.JSON(), nullable=False, server_default=sa.text("'[]'"))
        )
        batch.add_column(sa.Column("assigned_reviewer", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("resolution", sa.Text(), nullable=True))
        batch.add_column(
            sa.Column(
                "correction_delivery_status", sa.String(30), nullable=False, server_default="not_requested"
            )
        )
        batch.add_column(sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
        )
        batch.create_check_constraint(
            "ck_ck_academic_review_status",
            "status IN ('pending', 'open', 'assigned', 'corrected', 'confirmed', 'closed')",
        )
        batch.create_check_constraint(
            "ck_ck_review_delivery_status",
            "correction_delivery_status IN ('not_requested', 'requested', 'sent', 'failed')",
        )
        batch.create_foreign_key(
            "fk_ck_review_student", "education_students", ["student_id"], ["id"], ondelete="CASCADE"
        )
        batch.create_foreign_key(
            "fk_ck_review_course", "education_courses", ["course_id"], ["id"], ondelete="RESTRICT"
        )
        batch.create_foreign_key(
            "fk_ck_review_curriculum",
            "course_knowledge_curricula",
            ["curriculum_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_ck_review_paper", "course_knowledge_papers", ["paper_id"], ["id"], ondelete="SET NULL"
        )
        batch.create_foreign_key(
            "fk_ck_review_batch", "education_batches", ["batch_id"], ["id"], ondelete="RESTRICT"
        )
        batch.create_foreign_key(
            "fk_ck_review_reviewer", "users", ["assigned_reviewer"], ["id"], ondelete="SET NULL"
        )

    op.create_table(
        "course_knowledge_practice_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("agent_id", sa.Uuid(), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "student_id",
            sa.Uuid(),
            sa.ForeignKey("education_students.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "enrollment_id",
            sa.Uuid(),
            sa.ForeignKey("education_enrollments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "paper_id",
            sa.Uuid(),
            sa.ForeignKey("course_knowledge_papers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer_key", sa.Text(), nullable=False),
        sa.Column("student_answer", sa.Text(), nullable=True),
        sa.Column("is_correct", sa.Boolean(), nullable=True),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("workspace_id", "agent_id", "idempotency_key", name="uq_ck_practice_idempotency"),
        sa.CheckConstraint("status IN ('open', 'answered')", name="ck_ck_practice_status"),
    )
    op.create_table(
        "course_knowledge_progress",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("agent_id", sa.Uuid(), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "student_id",
            sa.Uuid(),
            sa.ForeignKey("education_students.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "enrollment_id",
            sa.Uuid(),
            sa.ForeignKey("education_enrollments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "paper_id",
            sa.Uuid(),
            sa.ForeignKey("course_knowledge_papers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("questions_asked", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("practice_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("objective_answers_correct", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("objective_answers_graded", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("learning_status", sa.String(20), nullable=False, server_default="not_started"),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("enrollment_id", "paper_id", name="uq_ck_progress_enrollment_paper"),
        sa.CheckConstraint(
            "learning_status IN ('not_started', 'practicing', 'review_needed')", name="ck_ck_learning_status"
        ),
    )
    for table in ("course_knowledge_practice_attempts", "course_knowledge_progress"):
        op.create_index(f"ix_{table}_scope", table, ["tenant_id", "workspace_id", "agent_id", "student_id"])


def downgrade() -> None:
    op.drop_table("course_knowledge_progress")
    op.drop_table("course_knowledge_practice_attempts")
    with op.batch_alter_table("course_knowledge_academic_reviews") as batch:
        batch.drop_constraint("ck_ck_review_delivery_status", type_="check")
        batch.drop_constraint("ck_ck_academic_review_status", type_="check")
        for column in (
            "updated_at",
            "reviewed_at",
            "correction_delivery_status",
            "resolution",
            "assigned_reviewer",
            "external_evidence",
            "internal_evidence",
            "answer",
            "batch_id",
            "paper_id",
            "curriculum_id",
            "course_id",
            "student_id",
        ):
            batch.drop_column(column)
    with op.batch_alter_table("course_knowledge_study_selections") as batch:
        batch.drop_constraint("ck_ck_selection_revision", type_="check")
        batch.drop_constraint("ck_ck_selection_interaction_state", type_="check")
        for column in (
            "selection_revision",
            "menu_expires_at",
            "menu_created_at",
            "menu_id",
            "pending_question",
            "interaction_state",
        ):
            batch.drop_column(column)
