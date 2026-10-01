"""Persist Education course-menu state and pending questions."""

import sqlalchemy as sa
from alembic import op

revision = "0048_education_tutor_interaction_state"
down_revision = "0047_education_knowledge_releases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("education_tutor_contexts") as batch:
        batch.add_column(
            sa.Column(
                "interaction_state",
                sa.String(40),
                nullable=False,
                server_default="ready_for_question",
            )
        )
        batch.add_column(sa.Column("pending_question", sa.Text(), nullable=True))
        batch.add_column(
            sa.Column("selection_revision", sa.Integer(), nullable=False, server_default="0")
        )
        batch.create_check_constraint(
            "ck_education_tutor_context_interaction_state",
            "interaction_state IN ('awaiting_course_selection', 'awaiting_paper_selection', "
            "'awaiting_quiz_answer', 'ready_for_question')",
        )


def downgrade() -> None:
    with op.batch_alter_table("education_tutor_contexts") as batch:
        batch.drop_constraint("ck_education_tutor_context_interaction_state", type_="check")
        batch.drop_column("selection_revision")
        batch.drop_column("pending_question")
        batch.drop_column("interaction_state")
