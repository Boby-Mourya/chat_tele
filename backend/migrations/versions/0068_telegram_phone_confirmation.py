"""Persist staff confirmation of a student's Telegram phone number."""
import sqlalchemy as sa
from alembic import op

revision = "0068_telegram_phone_confirmation"
down_revision = "0067_telegram_phone_enrollment"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("education_students", sa.Column("telegram_phone_verified", sa.Boolean(), nullable=False, server_default=sa.false()))

def downgrade():
    op.drop_column("education_students", "telegram_phone_verified")
