"""Persist signed WhatsApp delivery evidence.

Revision ID: 0039_whatsapp_delivery_receipts
Revises: 0038_outbox_webhook_timing_index
"""

import sqlalchemy as sa
from alembic import op

revision = "0039_whatsapp_delivery_receipts"
down_revision = "0038_outbox_webhook_timing_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "template_payload" not in {
        column["name"] for column in sa.inspect(bind).get_columns("whatsapp_outbound_deliveries")
    }:
        op.add_column("whatsapp_outbound_deliveries", sa.Column("template_payload", sa.JSON(), nullable=True))
    if "whatsapp_delivery_receipts" not in sa.inspect(bind).get_table_names():
        op.create_table(
            "whatsapp_delivery_receipts",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column(
                "workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column(
                "connection_id",
                sa.Uuid(),
                sa.ForeignKey("whatsapp_connections.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("provider_message_id", sa.String(160), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("provider_timestamp", sa.DateTime(timezone=True), nullable=False),
            sa.Column("error_code", sa.String(40)),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint(
                "connection_id", "provider_message_id", "status", name="uq_wa_delivery_receipt"
            ),
        )
        op.create_index(
            "ix_wa_delivery_receipt_scope",
            "whatsapp_delivery_receipts",
            ["tenant_id", "workspace_id", "connection_id", "created_at"],
        )

    if bind.dialect.name == "postgresql":
        op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON whatsapp_delivery_receipts TO northstar_app")
        op.execute("ALTER TABLE whatsapp_delivery_receipts ENABLE ROW LEVEL SECURITY")
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON whatsapp_delivery_receipts")
        op.execute(
            "CREATE POLICY tenant_isolation ON whatsapp_delivery_receipts "
            "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
            "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
        )


def downgrade() -> None:
    op.drop_column("whatsapp_outbound_deliveries", "template_payload")
    op.drop_table("whatsapp_delivery_receipts")
