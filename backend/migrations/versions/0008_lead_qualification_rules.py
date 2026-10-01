"""Add tenant-configurable lead qualification rules.

Revision ID: 0008_lead_qualification_rules
Revises: 0007_channel_connections
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_lead_qualification_rules"
down_revision = "0007_channel_connections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lead_qualification_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("conditions_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("actions_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_lead_qualification_rule_name"),
    )
    op.create_index("ix_lead_qualification_rule_tenant_id", "lead_qualification_rules", ["tenant_id"])
    op.create_index(
        "ix_lead_qualification_rules_active",
        "lead_qualification_rules",
        ["tenant_id", "enabled", "priority"],
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute('ALTER TABLE "lead_qualification_rules" ENABLE ROW LEVEL SECURITY')
        op.execute(
            'CREATE POLICY tenant_isolation ON "lead_qualification_rules" '
            "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
            "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
        )
        op.execute('GRANT SELECT, INSERT, UPDATE, DELETE ON "lead_qualification_rules" TO northstar_app')


def downgrade() -> None:
    op.drop_table("lead_qualification_rules")
