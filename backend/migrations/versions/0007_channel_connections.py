"""Add provider-neutral channel connections.

Revision ID: 0007_channel_connections
Revises: 0006_crm_circuit_breaker
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_channel_connections"
down_revision = "0006_crm_circuit_breaker"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "channel_connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("public_id", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(60), nullable=False, server_default="custom"),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="draft"),
        sa.Column("credentials_encrypted", sa.LargeBinary()),
        sa.Column("credentials_ref", sa.String(500)),
        sa.Column("configuration_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("last_health_at", sa.DateTime(timezone=True)),
        sa.Column("last_event_at", sa.DateTime(timezone=True)),
        sa.Column("last_failure_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(1000)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "public_id", name="uq_channel_connection_public_id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_channel_connection_name"),
    )
    op.create_index("ix_channel_connections_tenant_id", "channel_connections", ["tenant_id"])
    op.create_index(
        "ix_channel_connections_provider",
        "channel_connections",
        ["tenant_id", "provider", "status"],
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute('ALTER TABLE "channel_connections" ENABLE ROW LEVEL SECURITY')
        op.execute(
            'CREATE POLICY tenant_isolation ON "channel_connections" '
            "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
            "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
        )
        op.execute('GRANT SELECT, INSERT, UPDATE, DELETE ON "channel_connections" TO northstar_app')


def downgrade() -> None:
    op.drop_table("channel_connections")
