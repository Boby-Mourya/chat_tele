"""Index webhook outbox timing lookups.

Revision ID: 0038_outbox_webhook_timing_index
Revises: 0037_channel_delivery_attempts
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0038_outbox_webhook_timing_index"
down_revision = "0037_channel_delivery_attempts"
branch_labels = None
depends_on = None

_INDEX_NAME = "ix_outbox_webhook_pending_lookup"
_CREATE_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS ix_outbox_webhook_pending_lookup ON outbox_events "
    "(tenant_id, aggregate_type, event_type, replace(aggregate_id, '-', ''), occurred_at)"
)
_DROP_INDEX_SQL = "DROP INDEX IF EXISTS ix_outbox_webhook_pending_lookup"


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "outbox_events" not in tables:
        return

    op.execute(sa.text(_CREATE_INDEX_SQL))


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "outbox_events" not in tables:
        return

    op.execute(sa.text(_DROP_INDEX_SQL))
