"""Add authenticated Northstar Help Center storage.

Revision ID: 0005_help_center
Revises: 0004_whatsapp_per_agent
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import HALFVEC

from northstar_api.models import EMBEDDING_DIMENSION

revision = "0005_help_center"
down_revision = "0004_whatsapp_per_agent"
branch_labels = None
depends_on = None

TENANT_HELP_TABLES = (
    "help_article_feedback",
    "help_events",
    "help_support_requests",
)


def upgrade() -> None:
    op.create_table(
        "help_categories",
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("icon", sa.String(length=80), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_help_categories_slug", "help_categories", ["slug"], unique=True)
    op.create_index("ix_help_categories_sort_order", "help_categories", ["sort_order"], unique=False)
    op.create_index("ix_help_categories_is_active", "help_categories", ["is_active"], unique=False)

    op.create_table(
        "help_articles",
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("summary", sa.String(length=1000), nullable=False),
        sa.Column("body_markdown", sa.Text(), nullable=False),
        sa.Column("keywords_json", sa.JSON(), nullable=False),
        sa.Column("audience_roles_json", sa.JSON(), nullable=False),
        sa.Column("featured", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("reading_minutes", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["category_id"], ["help_categories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_help_articles_slug", "help_articles", ["slug"], unique=True)
    op.create_index("ix_help_articles_category_id", "help_articles", ["category_id"], unique=False)
    op.create_index("ix_help_articles_featured", "help_articles", ["featured"], unique=False)
    op.create_index("ix_help_articles_status", "help_articles", ["status"], unique=False)
    op.create_index("ix_help_articles_content_hash", "help_articles", ["content_hash"], unique=False)
    op.create_index("ix_help_articles_published_at", "help_articles", ["published_at"], unique=False)
    op.create_index(
        "ix_help_articles_category_status",
        "help_articles",
        ["category_id", "status", "sort_order"],
        unique=False,
    )

    op.create_table(
        "help_article_chunks",
        sa.Column("article_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("heading_path", sa.String(length=500), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding_model", sa.String(length=200), nullable=True),
        sa.Column("embedding", HALFVEC(EMBEDDING_DIMENSION), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["article_id"], ["help_articles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("article_id", "chunk_index", name="uq_help_article_chunks_article_chunk"),
    )
    op.create_index("ix_help_article_chunks_article_id", "help_article_chunks", ["article_id"], unique=False)
    op.create_index(
        "ix_help_article_chunks_article", "help_article_chunks", ["article_id", "chunk_index"], unique=False
    )

    op.create_table(
        "help_article_feedback",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("article_id", sa.Uuid(), nullable=False),
        sa.Column("helpful", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(length=40), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["article_id"], ["help_articles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "user_id", "article_id", name="uq_help_feedback_tenant_user_article"
        ),
    )
    op.create_index("ix_help_article_feedback_tenant_id", "help_article_feedback", ["tenant_id"], unique=False)
    op.create_index("ix_help_article_feedback_user_id", "help_article_feedback", ["user_id"], unique=False)
    op.create_index("ix_help_article_feedback_article_id", "help_article_feedback", ["article_id"], unique=False)
    op.create_index(
        "ix_help_feedback_tenant_article",
        "help_article_feedback",
        ["tenant_id", "article_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "help_events",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("article_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("query", sa.String(length=300), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["article_id"], ["help_articles.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_help_events_tenant_id", "help_events", ["tenant_id"], unique=False)
    op.create_index("ix_help_events_user_id", "help_events", ["user_id"], unique=False)
    op.create_index("ix_help_events_article_id", "help_events", ["article_id"], unique=False)
    op.create_index("ix_help_events_event_type", "help_events", ["event_type"], unique=False)
    op.create_index("ix_help_events_created_at", "help_events", ["created_at"], unique=False)
    op.create_index("ix_help_events_tenant_created", "help_events", ["tenant_id", "created_at"], unique=False)
    op.create_index("ix_help_events_article_type", "help_events", ["article_id", "event_type"], unique=False)

    op.create_table(
        "help_support_requests",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("requester_role", sa.String(length=32), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("context_path", sa.String(length=500), nullable=True),
        sa.Column("requester_email", sa.String(length=320), nullable=False),
        sa.Column("support_destination", sa.String(length=320), nullable=False),
        sa.Column("diagnostics_json", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_help_support_requests_tenant_id", "help_support_requests", ["tenant_id"], unique=False)
    op.create_index("ix_help_support_requests_user_id", "help_support_requests", ["user_id"], unique=False)
    op.create_index("ix_help_support_requests_category", "help_support_requests", ["category"], unique=False)
    op.create_index("ix_help_support_requests_status", "help_support_requests", ["status"], unique=False)
    op.create_index(
        "ix_help_support_tenant_created", "help_support_requests", ["tenant_id", "created_at"], unique=False
    )
    op.create_index(
        "ix_help_support_tenant_user",
        "help_support_requests",
        ["tenant_id", "user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_help_support_tenant_status",
        "help_support_requests",
        ["tenant_id", "status", "created_at"],
        unique=False,
    )

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_help_article_chunks_embedding_hnsw "
        "ON help_article_chunks USING hnsw (embedding halfvec_cosine_ops) WHERE embedding IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_help_articles_fts ON help_articles USING gin "
        "(to_tsvector('simple', title || ' ' || summary || ' ' || body_markdown))"
    )
    for table in TENANT_HELP_TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY tenant_isolation ON "{table}" '
            "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
            "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
        )
    op.execute(
        "GRANT SELECT ON help_categories, help_articles, help_article_chunks TO northstar_app"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON help_article_feedback, help_events, help_support_requests "
        "TO northstar_app"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_help_articles_fts")
        op.execute("DROP INDEX IF EXISTS ix_help_article_chunks_embedding_hnsw")
    op.drop_table("help_support_requests")
    op.drop_table("help_events")
    op.drop_table("help_article_feedback")
    op.drop_table("help_article_chunks")
    op.drop_table("help_articles")
    op.drop_table("help_categories")
