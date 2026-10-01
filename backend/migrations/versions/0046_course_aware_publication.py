"""Add review and publication state to Education knowledge assignments."""

from alembic import op
import sqlalchemy as sa

revision = "0046_course_aware_publication"
down_revision = "0045_multi_course_education_tutor"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("education_knowledge_scopes") as batch:
        batch.add_column(sa.Column("selected_block_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
        batch.add_column(sa.Column("topic_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
        batch.add_column(sa.Column("material_type", sa.String(40), nullable=False, server_default="notes"))
        batch.add_column(sa.Column("extraction_revision", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("mapping_revision", sa.Integer(), nullable=False, server_default="1"))
        # Existing rows were already student-visible before this migration. Keep
        # that compatibility; all assignments created by the revised API start
        # as draft and require explicit approval/publication.
        batch.add_column(sa.Column("approval_status", sa.String(20), nullable=False, server_default="published"))
        batch.add_column(sa.Column("approved_by", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key(
            "fk_education_knowledge_scopes_approved_by_users",
            "users",
            ["approved_by"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_check_constraint(
            "ck_education_knowledge_scope_approval_status",
            "approval_status IN ('draft', 'approved', 'published', 'withdrawn')",
        )
        batch.create_index(
            "ix_education_knowledge_scope_publication",
            ["tenant_id", "workspace_id", "agent_id", "approval_status", "withdrawn_at"],
        )


def downgrade() -> None:
    with op.batch_alter_table("education_knowledge_scopes") as batch:
        batch.drop_index("ix_education_knowledge_scope_publication")
        batch.drop_constraint("ck_education_knowledge_scope_approval_status", type_="check")
        batch.drop_constraint("fk_education_knowledge_scopes_approved_by_users", type_="foreignkey")
        batch.drop_column("withdrawn_at")
        batch.drop_column("published_at")
        batch.drop_column("approved_at")
        batch.drop_column("approved_by")
        batch.drop_column("approval_status")
        batch.drop_column("mapping_revision")
        batch.drop_column("extraction_revision")
        batch.drop_column("material_type")
        batch.drop_column("topic_ids")
        batch.drop_column("selected_block_ids")
