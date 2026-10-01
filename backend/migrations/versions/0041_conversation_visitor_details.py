"""Visitor contact and website attribution."""
import sqlalchemy as sa
from alembic import op

revision = "0041_conversation_visitor_details"
down_revision = "0040_whatsapp_account_inventory"
branch_labels = None
depends_on = None

def upgrade():
    if "visitor_details" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("conversations")}:
        op.add_column("conversations", sa.Column("visitor_details", sa.JSON(), nullable=False, server_default="{}"))

def downgrade():
    op.drop_column("conversations", "visitor_details")
