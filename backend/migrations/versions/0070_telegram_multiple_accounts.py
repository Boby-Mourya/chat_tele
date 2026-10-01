"""Allow independent Telegram bot accounts per agent."""
import sqlalchemy as sa
from alembic import op

revision = "0070_telegram_multiple_accounts"
down_revision = "0069_telegram_managed_bots"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("telegram_provisioning") as batch:
        batch.drop_constraint("uq_telegram_provisioning_agent_id", type_="unique")
        batch.create_index("ix_telegram_provisioning_agent_id", ["agent_id"])
        batch.create_unique_constraint("uq_telegram_provisioning_connection_id", ["connection_id"])


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT agent_id FROM telegram_provisioning GROUP BY agent_id HAVING COUNT(*) > 1 LIMIT 1")).first():
        raise RuntimeError("Multiple Telegram accounts exist; resolve them before downgrading")
    with op.batch_alter_table("telegram_provisioning") as batch:
        batch.drop_constraint("uq_telegram_provisioning_connection_id", type_="unique")
        batch.drop_index("ix_telegram_provisioning_agent_id")
        batch.create_unique_constraint("uq_telegram_provisioning_agent_id", ["agent_id"])
