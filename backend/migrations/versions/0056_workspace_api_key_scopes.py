"""Persist workspace API key scopes.

Revision ID: 0056_workspace_api_key_scopes
Revises: 0055_workspace_brand_domain_resolver
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0056_workspace_api_key_scopes"
down_revision = "0055_workspace_brand_domain_resolver"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("workspace_api_keys") as batch:
        batch.add_column(sa.Column("scopes", sa.JSON(), nullable=True))
    op.execute(
        "UPDATE workspace_api_keys SET scopes = '[\"conversations:read\", \"agents:read\", \"analytics:read\"]' WHERE scopes IS NULL"
    )
    with op.batch_alter_table("workspace_api_keys") as batch:
        batch.alter_column("scopes", existing_type=sa.JSON(), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("workspace_api_keys") as batch:
        batch.drop_column("scopes")
