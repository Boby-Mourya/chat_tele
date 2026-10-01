"""Workspace WhatsApp accounts and unassigned number inventory."""

import sqlalchemy as sa
from alembic import op

from northstar_api.models import Base

revision = "0040_whatsapp_account_inventory"
down_revision = "0039_whatsapp_delivery_receipts"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    Base.metadata.tables["whatsapp_business_accounts"].create(bind=bind, checkfirst=True)
    columns = {item["name"] for item in sa.inspect(bind).get_columns("whatsapp_connections")}
    with op.batch_alter_table("whatsapp_connections") as batch:
        batch.alter_column("agent_id", existing_type=sa.Uuid(), nullable=True)
        if "business_account_id" not in columns:
            batch.add_column(sa.Column("business_account_id", sa.Uuid(), nullable=True))
            batch.create_foreign_key(
                "fk_whatsapp_connection_account",
                "whatsapp_business_accounts",
                ["business_account_id"],
                ["id"],
                ondelete="RESTRICT",
            )
            batch.create_index("ix_whatsapp_connections_business_account_id", ["business_account_id"])
    if bind.dialect.name == "postgresql":
        op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON whatsapp_business_accounts TO northstar_app")
        op.execute("ALTER TABLE whatsapp_business_accounts ENABLE ROW LEVEL SECURITY")
        op.execute(
            "CREATE POLICY tenant_isolation ON whatsapp_business_accounts USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
        )
        op.execute(
            "CREATE FUNCTION northstar_resolve_whatsapp_account(requested_id uuid) RETURNS uuid LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$ SELECT tenant_id FROM whatsapp_business_accounts WHERE id = requested_id LIMIT 1 $$"
        )
        op.execute("REVOKE ALL ON FUNCTION northstar_resolve_whatsapp_account(uuid) FROM PUBLIC")
        op.execute("GRANT EXECUTE ON FUNCTION northstar_resolve_whatsapp_account(uuid) TO northstar_app")


def downgrade():
    raise RuntimeError("Unassignable numbers must be migrated before reverting WhatsApp account inventory")
