"""Add tenant subscription foundation.

Revision ID: 0029_tenant_subscriptions
Revises: 0028_workspace_api_keys
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op

revision = "0029_tenant_subscriptions"
down_revision = "0028_workspace_api_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "tenant_subscriptions" not in tables:
        op.create_table(
            "tenant_subscriptions",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("plan", sa.String(length=40), nullable=False, server_default="starter"),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="active"),
            sa.Column("provider", sa.String(length=40), nullable=True),
            sa.Column("provider_customer_id", sa.String(length=160), nullable=True),
            sa.Column("provider_subscription_id", sa.String(length=160), nullable=True),
            sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
            sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
            sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("past_due_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tenant_id", name="uq_tenant_subscriptions_tenant_id"),
        )
        op.create_index(
            "ix_tenant_subscriptions_tenant_id",
            "tenant_subscriptions",
            ["tenant_id"],
        )
        op.create_index(
            "ix_tenant_subscriptions_status",
            "tenant_subscriptions",
            ["status"],
        )
        op.create_index(
            "ix_tenant_subscriptions_provider_customer",
            "tenant_subscriptions",
            ["provider", "provider_customer_id"],
        )

    tenants = bind.execute(sa.text("SELECT id, plan FROM tenants")).all()
    existing_tenant_ids = {
        row[0]
        for row in bind.execute(sa.text("SELECT tenant_id FROM tenant_subscriptions")).all()
    }
    subscription_table = sa.table(
        "tenant_subscriptions",
        sa.column("id", sa.Uuid()),
        sa.column("tenant_id", sa.Uuid()),
        sa.column("plan", sa.String()),
        sa.column("status", sa.String()),
        sa.column("cancel_at_period_end", sa.Boolean()),
    )
    for tenant_id, plan in tenants:
        if tenant_id in existing_tenant_ids:
            continue
        normalized_tenant_id = (
            tenant_id if isinstance(tenant_id, uuid.UUID) else uuid.UUID(str(tenant_id))
        )
        bind.execute(
            subscription_table.insert().values(
                id=uuid.uuid4(),
                tenant_id=normalized_tenant_id,
                plan=(plan or "starter").strip().lower(),
                status="active",
                cancel_at_period_end=False,
            )
        )

    if bind.dialect.name == "postgresql":
        for role in ("northstar_app", "northstar_service"):
            op.execute(
                f'GRANT SELECT, INSERT, UPDATE, DELETE ON "tenant_subscriptions" TO "{role}"'
            )


def downgrade() -> None:
    bind = op.get_bind()
    if "tenant_subscriptions" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("tenant_subscriptions")
