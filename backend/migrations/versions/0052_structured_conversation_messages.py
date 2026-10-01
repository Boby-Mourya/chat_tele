"""Persist operator-selected outbound message formats."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0052_structured_conversation_messages"
down_revision = "0051_complete_education_tutor_workflows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("messages") as batch:
        batch.add_column(sa.Column("content_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))


def downgrade() -> None:
    with op.batch_alter_table("messages") as batch:
        batch.drop_column("content_json")
