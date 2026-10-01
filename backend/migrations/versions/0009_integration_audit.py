"""Add immutable integration audit events.

Revision ID: 0009_integration_audit
Revises: 0008_lead_qualification_rules
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_integration_audit"
down_revision = "0008_lead_qualification_rules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "integration_audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid()),
        sa.Column("action", sa.String(160), nullable=False),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("entity_id", sa.String(160), nullable=False),
        sa.Column("before_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("after_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("request_id", sa.String(128)),
        sa.Column("ip_address", sa.String(80)),
        sa.Column("user_agent", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_integration_audit_tenant_id", "integration_audit_events", ["tenant_id"])
    op.create_index("ix_integration_audit_actor_user_id", "integration_audit_events", ["actor_user_id"])
    op.create_index("ix_integration_audit_request_id", "integration_audit_events", ["request_id"])
    op.create_index("ix_integration_audit_scope", "integration_audit_events", ["tenant_id", "created_at"])
    op.create_index(
        "ix_integration_audit_entity",
        "integration_audit_events",
        ["tenant_id", "entity_type", "entity_id"],
    )
    op.create_index(
        "ix_integration_audit_action",
        "integration_audit_events",
        ["tenant_id", "action", "created_at"],
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute('ALTER TABLE "integration_audit_events" ENABLE ROW LEVEL SECURITY')
        op.execute(
            'CREATE POLICY tenant_isolation ON "integration_audit_events" '
            "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
            "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
        )
        op.execute('GRANT SELECT, INSERT ON "integration_audit_events" TO northstar_app')
        op.execute('REVOKE UPDATE, DELETE ON "integration_audit_events" FROM northstar_app')


def downgrade() -> None:
    op.drop_table("integration_audit_events")
