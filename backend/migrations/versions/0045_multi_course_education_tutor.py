"""Add multi-course curricula, papers, tutor routing, progress, and review records."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op

revision = "0045_multi_course_education_tutor"
down_revision = "0044_hybrid_extraction_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    with op.batch_alter_table("education_courses") as batch:
        batch.add_column(sa.Column("awarding_body", sa.String(160), nullable=False, server_default=""))
        batch.add_column(sa.Column("jurisdiction", sa.String(80), nullable=False, server_default=""))
        batch.add_column(sa.Column("aliases", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))

    with op.batch_alter_table("education_students") as batch:
        batch.add_column(
            sa.Column("preferred_language", sa.String(80), nullable=False, server_default="English")
        )

    if "education_curricula" not in tables:
        op.create_table(
            "education_curricula",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("workspace_id", sa.Uuid(), nullable=False),
            sa.Column("course_id", sa.Uuid(), nullable=False),
            sa.Column("version", sa.String(80), nullable=False),
            sa.Column("name", sa.String(160), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("effective_from", sa.Date(), nullable=True),
            sa.Column("effective_to", sa.Date(), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint(
                "status IN ('active', 'archived')", name="ck_education_curricula_status"
            ),
            sa.CheckConstraint(
                "effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from",
                name="ck_education_curricula_date_range",
            ),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["course_id"], ["education_courses.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("course_id", "version", name="uq_education_curricula_course_version"),
        )
        for column in ("tenant_id", "workspace_id", "course_id"):
            op.create_index(f"ix_education_curricula_{column}", "education_curricula", [column])
        op.create_index(
            "ix_education_curricula_scope",
            "education_curricula",
            ["tenant_id", "workspace_id", "course_id", "status"],
        )

    course_table = sa.table(
        "education_courses",
        sa.column("id", sa.Uuid()),
        sa.column("tenant_id", sa.Uuid()),
        sa.column("workspace_id", sa.Uuid()),
        sa.column("name", sa.String()),
    )
    curriculum_table = sa.table(
        "education_curricula",
        sa.column("id", sa.Uuid()),
        sa.column("tenant_id", sa.Uuid()),
        sa.column("workspace_id", sa.Uuid()),
        sa.column("course_id", sa.Uuid()),
        sa.column("version", sa.String()),
        sa.column("name", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("status", sa.String()),
    )
    curriculum_by_course: dict[uuid.UUID, uuid.UUID] = {}
    for course in bind.execute(sa.select(course_table)).mappings():
        curriculum_id = uuid.uuid4()
        curriculum_by_course[course["id"]] = curriculum_id
        bind.execute(
            sa.insert(curriculum_table).values(
                id=curriculum_id,
                tenant_id=course["tenant_id"],
                workspace_id=course["workspace_id"],
                course_id=course["id"],
                version="LEGACY",
                name=f"{course['name']} legacy syllabus",
                description="Backfilled for multi-course compatibility.",
                status="active",
            )
        )

    with op.batch_alter_table("education_batches") as batch:
        batch.add_column(sa.Column("curriculum_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_ed_batches_curriculum",
            "education_curricula",
            ["curriculum_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_index("ix_education_batches_curriculum_id", ["curriculum_id"])

    batch_table = sa.table(
        "education_batches",
        sa.column("id", sa.Uuid()),
        sa.column("course_id", sa.Uuid()),
        sa.column("curriculum_id", sa.Uuid()),
    )
    for batch_row in bind.execute(sa.select(batch_table.c.id, batch_table.c.course_id)).mappings():
        curriculum_id = curriculum_by_course.get(batch_row["course_id"])
        if curriculum_id:
            bind.execute(
                sa.update(batch_table)
                .where(batch_table.c.id == batch_row["id"])
                .values(curriculum_id=curriculum_id)
            )

    if "education_papers" not in tables:
        op.create_table(
            "education_papers",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("workspace_id", sa.Uuid(), nullable=False),
            sa.Column("course_id", sa.Uuid(), nullable=False),
            sa.Column("curriculum_id", sa.Uuid(), nullable=False),
            sa.Column("code", sa.String(40), nullable=False),
            sa.Column("name", sa.String(160), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("aliases", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint("status IN ('active', 'archived')", name="ck_education_papers_status"),
            sa.CheckConstraint("sequence >= 0", name="ck_education_papers_sequence"),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["course_id"], ["education_courses.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["curriculum_id"], ["education_curricula.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("curriculum_id", "code", name="uq_education_papers_curriculum_code"),
        )
        for column in ("tenant_id", "workspace_id", "course_id", "curriculum_id"):
            op.create_index(f"ix_education_papers_{column}", "education_papers", [column])
        op.create_index(
            "ix_education_papers_scope",
            "education_papers",
            ["tenant_id", "workspace_id", "course_id", "curriculum_id", "status"],
        )

    with op.batch_alter_table("education_knowledge_scopes") as batch:
        batch.add_column(sa.Column("curriculum_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("paper_id", sa.Uuid(), nullable=True))
        batch.alter_column("batch_id", existing_type=sa.Uuid(), nullable=True)
        batch.create_foreign_key(
            "fk_ed_knowledge_scope_curriculum",
            "education_curricula",
            ["curriculum_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_ed_knowledge_scope_paper",
            "education_papers",
            ["paper_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_index("ix_education_knowledge_scopes_curriculum_id", ["curriculum_id"])
        batch.create_index("ix_education_knowledge_scopes_paper_id", ["paper_id"])

    scope_table = sa.table(
        "education_knowledge_scopes",
        sa.column("id", sa.Uuid()),
        sa.column("batch_id", sa.Uuid()),
        sa.column("curriculum_id", sa.Uuid()),
    )
    batch_curricula = {
        row["id"]: row["curriculum_id"]
        for row in bind.execute(sa.select(batch_table.c.id, batch_table.c.curriculum_id)).mappings()
    }
    for scope in bind.execute(sa.select(scope_table.c.id, scope_table.c.batch_id)).mappings():
        curriculum_id = batch_curricula.get(scope["batch_id"])
        if curriculum_id:
            bind.execute(
                sa.update(scope_table)
                .where(scope_table.c.id == scope["id"])
                .values(curriculum_id=curriculum_id)
            )

    with op.batch_alter_table("education_conversation_contexts") as batch:
        batch.add_column(sa.Column("curriculum_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("paper_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_ed_conversation_context_curriculum",
            "education_curricula",
            ["curriculum_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_ed_conversation_context_paper",
            "education_papers",
            ["paper_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_index("ix_education_conversation_contexts_curriculum_id", ["curriculum_id"])
        batch.create_index("ix_education_conversation_contexts_paper_id", ["paper_id"])

    conversation_context = sa.table(
        "education_conversation_contexts",
        sa.column("id", sa.Uuid()),
        sa.column("batch_id", sa.Uuid()),
        sa.column("curriculum_id", sa.Uuid()),
    )
    for context in bind.execute(
        sa.select(conversation_context.c.id, conversation_context.c.batch_id)
    ).mappings():
        curriculum_id = batch_curricula.get(context["batch_id"])
        if curriculum_id:
            bind.execute(
                sa.update(conversation_context)
                .where(conversation_context.c.id == context["id"])
                .values(curriculum_id=curriculum_id)
            )

    _create_tutor_tables()


def _create_tutor_tables() -> None:
    op.create_table(
        "education_tutor_contexts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("active_enrollment_id", sa.Uuid(), nullable=True),
        sa.Column("active_paper_id", sa.Uuid(), nullable=True),
        sa.Column("pending_enrollment_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("preferred_language", sa.String(80), nullable=True),
        sa.Column("selected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["education_students.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["active_enrollment_id"], ["education_enrollments.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["active_paper_id"], ["education_papers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "agent_id", "student_id", name="uq_education_tutor_context_student_agent"
        ),
    )
    op.create_index(
        "ix_education_tutor_context_scope",
        "education_tutor_contexts",
        ["tenant_id", "workspace_id", "agent_id", "student_id"],
    )

    op.create_table(
        "education_paper_progress",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("enrollment_id", sa.Uuid(), nullable=False),
        sa.Column("paper_id", sa.Uuid(), nullable=False),
        sa.Column("questions_asked", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("practice_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("correct_objective_answers", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="not_started"),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('not_started', 'in_progress', 'practiced')",
            name="ck_education_paper_progress_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["education_students.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["enrollment_id"], ["education_enrollments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["paper_id"], ["education_papers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "enrollment_id", "paper_id", name="uq_education_paper_progress_enrollment_paper"
        ),
    )
    op.create_index(
        "ix_education_paper_progress_student",
        "education_paper_progress",
        ["workspace_id", "student_id", "updated_at"],
    )

    op.create_table(
        "education_practice_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("enrollment_id", sa.Uuid(), nullable=False),
        sa.Column("paper_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("student_answer", sa.Text(), nullable=True),
        sa.Column("expected_answer", sa.Text(), nullable=True),
        sa.Column("is_correct", sa.Boolean(), nullable=True),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["education_students.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["enrollment_id"], ["education_enrollments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["paper_id"], ["education_papers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_education_practice_attempt_scope",
        "education_practice_attempts",
        ["workspace_id", "student_id", "paper_id", "created_at"],
    )

    op.create_table(
        "education_academic_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("enrollment_id", sa.Uuid(), nullable=False),
        sa.Column("course_id", sa.Uuid(), nullable=False),
        sa.Column("curriculum_id", sa.Uuid(), nullable=True),
        sa.Column("paper_id", sa.Uuid(), nullable=True),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("assistant_message_id", sa.Uuid(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("confidence_reason", sa.String(120), nullable=False),
        sa.Column("correction", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('open', 'resolved', 'dismissed')",
            name="ck_education_academic_reviews_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["education_students.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["enrollment_id"], ["education_enrollments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["course_id"], ["education_courses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["curriculum_id"], ["education_curricula.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["paper_id"], ["education_papers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assistant_message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "assistant_message_id", name="uq_education_academic_review_assistant_message"
        ),
    )
    op.create_index(
        "ix_education_academic_review_queue",
        "education_academic_reviews",
        ["workspace_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("education_academic_reviews")
    op.drop_table("education_practice_attempts")
    op.drop_table("education_paper_progress")
    op.drop_table("education_tutor_contexts")
    with op.batch_alter_table("education_conversation_contexts") as batch:
        batch.drop_column("paper_id")
        batch.drop_column("curriculum_id")
    with op.batch_alter_table("education_knowledge_scopes") as batch:
        batch.alter_column("batch_id", existing_type=sa.Uuid(), nullable=False)
        batch.drop_column("paper_id")
        batch.drop_column("curriculum_id")
    op.drop_table("education_papers")
    with op.batch_alter_table("education_batches") as batch:
        batch.drop_column("curriculum_id")
    op.drop_table("education_curricula")
    with op.batch_alter_table("education_students") as batch:
        batch.drop_column("preferred_language")
    with op.batch_alter_table("education_courses") as batch:
        batch.drop_column("aliases")
        batch.drop_column("jurisdiction")
        batch.drop_column("awarding_body")
