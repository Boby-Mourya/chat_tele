from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0035_education_upsell_leads"
down_revision = "0034_education_access_requests"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    inspector = inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return False
    return any(item["name"] == column for item in inspector.get_columns(table))


def upgrade() -> None:
    if not _column_exists("education_conversation_contexts", "sales_intent_detected"):
        op.add_column(
            "education_conversation_contexts",
            sa.Column(
                "sales_intent_detected",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )


def downgrade() -> None:
    if _column_exists("education_conversation_contexts", "sales_intent_detected"):
        op.drop_column("education_conversation_contexts", "sales_intent_detected")
