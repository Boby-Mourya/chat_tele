"""Merge the knowledge-review and LLM connection migration heads.

Revision ID: 0059_merge_llm_connection_heads
Revises: 0055_knowledge_source_review_status, 0058_llm_connections
"""

from collections.abc import Sequence

from alembic import op


revision: str = "0059_merge_llm_connection_heads"
down_revision: tuple[str, str] = (
    "0055_knowledge_source_review_status",
    "0058_llm_connections",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Merge the two existing migration branches."""


def downgrade() -> None:
    """Re-create the two migration heads when rolling back the merge."""
