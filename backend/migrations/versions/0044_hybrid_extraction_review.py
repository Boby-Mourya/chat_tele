"""Keep extraction review separate from searchable knowledge."""

import sqlalchemy as sa
from alembic import op

revision = "0044_hybrid_extraction_review"
down_revision = "0043_knowledge_training"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("knowledge_sources", sa.Column("extraction_key", sa.String(1000), nullable=True))
    op.add_column(
        "knowledge_sources", sa.Column("extraction_issue_count", sa.Integer(), nullable=False, server_default="0")
    )
    if op.get_bind().dialect.name == "postgresql":
        op.alter_column("knowledge_sources", "extraction_issue_count", server_default=None)


def downgrade() -> None:
    op.drop_column("knowledge_sources", "extraction_issue_count")
    op.drop_column("knowledge_sources", "extraction_key")
