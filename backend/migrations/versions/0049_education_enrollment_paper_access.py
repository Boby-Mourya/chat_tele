"""Add explicit curriculum and paper authority to Education enrollments."""

import sqlalchemy as sa
from alembic import op

revision = "0049_education_enrollment_paper_access"
down_revision = "0048_education_tutor_interaction_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("education_enrollments") as batch:
        batch.add_column(sa.Column("curriculum_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("all_papers", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.add_column(sa.Column("paper_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
        batch.add_column(sa.Column("authorization_revision", sa.Integer(), nullable=False, server_default="1"))
        batch.create_foreign_key(
            "fk_education_enrollments_curriculum",
            "education_curricula",
            ["curriculum_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_index("ix_education_enrollments_curriculum_id", ["curriculum_id"])

    op.execute(
        sa.text(
            "UPDATE education_enrollments SET curriculum_id = "
            "(SELECT curriculum_id FROM education_batches "
            "WHERE education_batches.id = education_enrollments.batch_id)"
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("education_enrollments") as batch:
        batch.drop_index("ix_education_enrollments_curriculum_id")
        batch.drop_constraint("fk_education_enrollments_curriculum", type_="foreignkey")
        batch.drop_column("authorization_revision")
        batch.drop_column("paper_ids")
        batch.drop_column("all_papers")
        batch.drop_column("curriculum_id")
