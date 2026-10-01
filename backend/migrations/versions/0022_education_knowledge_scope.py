"""Scope existing knowledge to Education Course + Batch access.

Revision ID: 0022_education_knowledge_scope
Revises: 0021_education_conversation_context
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0022_education_knowledge_scope"
down_revision = "0021_education_conversation_context"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "education_knowledge_scopes" in set(sa.inspect(bind).get_table_names()):
        return

    op.create_table(
        "education_knowledge_scopes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("fact_id", sa.Uuid(), nullable=True),
        sa.Column("course_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "(source_id IS NOT NULL AND fact_id IS NULL) OR "
            "(source_id IS NULL AND fact_id IS NOT NULL)",
            name="ck_education_knowledge_scope_target",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["knowledge_sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["fact_id"], ["knowledge_facts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["course_id"], ["education_courses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["batch_id"], ["education_batches.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id",
            "course_id",
            "batch_id",
            name="uq_education_knowledge_scope_source",
        ),
        sa.UniqueConstraint(
            "fact_id",
            "course_id",
            "batch_id",
            name="uq_education_knowledge_scope_fact",
        ),
    )
    for column in ("tenant_id", "workspace_id", "agent_id", "course_id", "batch_id"):
        op.create_index(
            f"ix_education_knowledge_scopes_{column}",
            "education_knowledge_scopes",
            [column],
        )
    op.create_index(
        "ix_education_knowledge_scope_lookup",
        "education_knowledge_scopes",
        ["tenant_id", "workspace_id", "agent_id", "course_id", "batch_id"],
    )
    op.create_index(
        "ix_education_knowledge_scope_source_id",
        "education_knowledge_scopes",
        ["source_id"],
    )
    op.create_index(
        "ix_education_knowledge_scope_fact_id",
        "education_knowledge_scopes",
        ["fact_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "education_knowledge_scopes" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("education_knowledge_scopes")
