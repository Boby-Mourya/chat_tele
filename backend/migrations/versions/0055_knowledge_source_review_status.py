"""Allow the extraction-review status on knowledge sources."""

import sqlalchemy as sa
from alembic import op

revision = "0055_knowledge_source_review_status"
down_revision = "0054_knowledge_audit_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Widen the legacy enum-backed VARCHAR(10) column without changing data."""
    op.alter_column(
        "knowledge_sources",
        "status",
        existing_type=sa.String(10),
        type_=sa.String(20),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "knowledge_sources",
        "status",
        existing_type=sa.String(20),
        type_=sa.String(10),
        existing_nullable=False,
    )
