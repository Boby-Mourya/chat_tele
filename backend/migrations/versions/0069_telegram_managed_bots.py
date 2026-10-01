"""Managed Telegram provisioning and management-event deduplication."""
import sqlalchemy as sa
from alembic import op

revision = "0069_telegram_managed_bots"
down_revision = "0068_telegram_phone_confirmation"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    op.create_table("telegram_provisioning",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", sa.Uuid(), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("connection_id", sa.Uuid(), sa.ForeignKey("channel_connections.id", ondelete="SET NULL")),
        sa.Column("nonce_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("nonce_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("telegram_user_id", sa.String(32)),
        sa.Column("request_id", sa.Integer(), nullable=False),
        sa.Column("bot_id", sa.String(32), unique=True),
        sa.Column("error", sa.String(250)),
    )
    op.create_index("ix_telegram_provisioning_telegram_user_id", "telegram_provisioning", ["telegram_user_id"])
    op.create_table("telegram_manager_updates",
        sa.Column("update_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )
    if bind.dialect.name == "postgresql":
        # Control-plane lookup precedes tenant selection. Only authenticated manager
        # webhook code may look up by nonce; customer reads always scope explicitly.
        op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON telegram_provisioning, telegram_manager_updates TO northstar_app")


def downgrade():
    op.drop_table("telegram_manager_updates")
    op.drop_table("telegram_provisioning")
