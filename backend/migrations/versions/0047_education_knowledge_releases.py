"""Immutable Education source versions, validation, artifacts, and releases."""

from alembic import op
import sqlalchemy as sa

revision = "0047_education_knowledge_releases"
down_revision = "0046_course_aware_publication"
branch_labels = None
depends_on = None


def _scope(table: str) -> None:
    op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
    op.create_index(f"ix_{table}_workspace_id", table, ["workspace_id"])


def upgrade() -> None:
    op.create_table(
        "education_source_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("processing_configuration", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["knowledge_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "version", name="uq_education_source_version"),
    )
    _scope("education_source_versions")
    op.create_index("ix_education_source_versions_source_id", "education_source_versions", ["source_id"])
    op.create_index("ix_education_source_versions_state", "education_source_versions", ["state"])

    with op.batch_alter_table("education_knowledge_scopes") as batch:
        batch.drop_constraint("uq_education_knowledge_scope_source", type_="unique")
        batch.drop_constraint("uq_education_knowledge_scope_fact", type_="unique")
        batch.add_column(sa.Column("source_version_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("assignment_revision", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("requires_release", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.create_foreign_key(
            "fk_ed_knowledge_scope_source_version",
            "education_source_versions",
            ["source_version_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_index("ix_education_knowledge_scopes_source_version_id", ["source_version_id"])
        batch.create_unique_constraint(
            "uq_education_knowledge_scope_source",
            ["source_id", "course_id", "curriculum_id", "paper_id", "batch_id"],
        )
        batch.create_unique_constraint(
            "uq_education_knowledge_scope_fact",
            ["fact_id", "course_id", "curriculum_id", "paper_id", "batch_id"],
        )

    op.create_table(
        "education_extracted_blocks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("source_version_id", sa.Uuid(), nullable=False),
        sa.Column("block_id", sa.String(120), nullable=False),
        sa.Column("parent_block_id", sa.String(120), nullable=True),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("extraction_revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_version_id"], ["education_source_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_version_id", "block_id", name="uq_education_extracted_block"),
    )
    _scope("education_extracted_blocks")
    op.create_index("ix_education_extracted_blocks_source_version_id", "education_extracted_blocks", ["source_version_id"])
    op.create_index("ix_education_extracted_block_order", "education_extracted_blocks", ["source_version_id", "ordinal"])

    op.create_table(
        "education_validation_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("source_version_id", sa.Uuid(), nullable=False),
        sa.Column("extraction_revision", sa.Integer(), nullable=False),
        sa.Column("mapping_revision", sa.Integer(), nullable=False),
        sa.Column("checks", sa.JSON(), nullable=False),
        sa.Column("issues", sa.JSON(), nullable=False),
        sa.Column("critical_issues_resolved", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_version_id"], ["education_source_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_version_id", "extraction_revision", "mapping_revision", name="uq_education_validation_report_revision"),
    )
    _scope("education_validation_reports")
    op.create_index("ix_education_validation_reports_source_version_id", "education_validation_reports", ["source_version_id"])

    op.create_table(
        "education_knowledge_releases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("course_id", sa.Uuid(), nullable=False),
        sa.Column("curriculum_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("index_verified", sa.Boolean(), nullable=False),
        sa.Column("activated_by", sa.Uuid(), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["course_id"], ["education_courses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["curriculum_id"], ["education_curricula.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["activated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", "course_id", "curriculum_id", "revision", name="uq_education_release_revision"),
    )
    _scope("education_knowledge_releases")
    for column in ("agent_id", "course_id", "curriculum_id", "status"):
        op.create_index(f"ix_education_knowledge_releases_{column}", "education_knowledge_releases", [column])
    op.create_index("ix_education_release_active", "education_knowledge_releases", ["tenant_id", "workspace_id", "agent_id", "course_id", "curriculum_id", "status"])

    op.create_table(
        "education_release_assignments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("release_id", sa.Uuid(), nullable=False),
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("assignment_revision", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["release_id"], ["education_knowledge_releases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assignment_id"], ["education_knowledge_scopes.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("release_id", "assignment_id", name="uq_education_release_assignment"),
    )
    op.create_index("ix_education_release_assignments_release_id", "education_release_assignments", ["release_id"])
    op.create_index("ix_education_release_assignments_assignment_id", "education_release_assignments", ["assignment_id"])

    op.create_table(
        "education_derived_learning_artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_type", sa.String(30), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("source_version_ids", sa.JSON(), nullable=False),
        sa.Column("source_block_ids", sa.JSON(), nullable=False),
        sa.Column("course_assignment_ids", sa.JSON(), nullable=False),
        sa.Column("generation_configuration_version", sa.String(80), nullable=False),
        sa.Column("review_status", sa.String(20), nullable=False),
        sa.Column("publication_status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    _scope("education_derived_learning_artifacts")
    op.create_index("ix_education_derived_learning_artifacts_agent_id", "education_derived_learning_artifacts", ["agent_id"])


def downgrade() -> None:
    op.drop_table("education_derived_learning_artifacts")
    op.drop_table("education_release_assignments")
    op.drop_table("education_knowledge_releases")
    op.drop_table("education_validation_reports")
    op.drop_table("education_extracted_blocks")
    with op.batch_alter_table("education_knowledge_scopes") as batch:
        batch.drop_constraint("uq_education_knowledge_scope_source", type_="unique")
        batch.drop_constraint("uq_education_knowledge_scope_fact", type_="unique")
        batch.drop_index("ix_education_knowledge_scopes_source_version_id")
        batch.drop_constraint(
            "fk_ed_knowledge_scope_source_version",
            type_="foreignkey",
        )
        batch.drop_column("requires_release")
        batch.drop_column("assignment_revision")
        batch.drop_column("source_version_id")
        batch.create_unique_constraint(
            "uq_education_knowledge_scope_source",
            ["source_id", "course_id", "batch_id"],
        )
        batch.create_unique_constraint(
            "uq_education_knowledge_scope_fact",
            ["fact_id", "course_id", "batch_id"],
        )
    op.drop_table("education_source_versions")
