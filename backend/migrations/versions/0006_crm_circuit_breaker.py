"""Persist CRM circuit-breaker state.

Revision ID: 0006_crm_circuit_breaker
Revises: 0005_lead_crm_platform
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_crm_circuit_breaker"
down_revision = "0005_lead_crm_platform"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_circuit_breakers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(24), nullable=False, server_default="closed"),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("opened_at", sa.DateTime(timezone=True)),
        sa.Column("open_until", sa.DateTime(timezone=True)),
        sa.Column("last_failure_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connection_id"], ["crm_connections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "connection_id", name="uq_crm_circuit_connection"),
    )
    op.create_index("ix_crm_circuit_tenant_id", "crm_circuit_breakers", ["tenant_id"])
    op.create_index("ix_crm_circuit_connection_id", "crm_circuit_breakers", ["connection_id"])
    op.create_index("ix_crm_circuit_open_until", "crm_circuit_breakers", ["open_until"])
    op.create_index("ix_crm_circuit_scope", "crm_circuit_breakers", ["tenant_id", "state", "open_until"])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute('ALTER TABLE "crm_circuit_breakers" ENABLE ROW LEVEL SECURITY')
        op.execute(
            'CREATE POLICY tenant_isolation ON "crm_circuit_breakers" '
            "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
            "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
        )
        op.execute('GRANT SELECT, INSERT, UPDATE, DELETE ON "crm_circuit_breakers" TO northstar_app')


def downgrade() -> None:
    op.drop_table("crm_circuit_breakers")
