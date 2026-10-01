"""Add first-class Agent purpose.

Revision ID: 0015_agent_purpose
Revises: 0014_workspace_channel_scope
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015_agent_purpose"
down_revision = "0014_workspace_channel_scope"
branch_labels = None
depends_on = None

PURPOSES = ("support", "lead_generation", "education")


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "agent_purpose_settings" not in tables:
        op.create_table(
            "agent_purpose_settings",
            sa.Column("agent_id", sa.Uuid(), nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("workspace_id", sa.Uuid(), nullable=False),
            sa.Column("purpose", sa.String(length=40), nullable=False, server_default="support"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint(
                "purpose IN ('support', 'lead_generation', 'education')",
                name="ck_agent_purpose_settings_purpose",
            ),
            sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("agent_id"),
            sa.UniqueConstraint("agent_id", name="uq_agent_purpose_settings_agent"),
        )
        op.create_index(
            "ix_agent_purpose_settings_scope",
            "agent_purpose_settings",
            ["tenant_id", "workspace_id", "purpose"],
        )
        op.create_index("ix_agent_purpose_settings_tenant_id", "agent_purpose_settings", ["tenant_id"])
        op.create_index("ix_agent_purpose_settings_workspace_id", "agent_purpose_settings", ["workspace_id"])

    # Existing Agents predate purpose semantics. Default them to Support rather
    # than guessing from names/instructions so no Agent is accidentally treated
    # as a Lead or Education Agent after deployment.
    meta = sa.MetaData()
    agents = sa.Table("agents", meta, autoload_with=bind)
    settings = sa.Table("agent_purpose_settings", meta, autoload_with=bind)
    existing = {row[0] for row in bind.execute(sa.select(settings.c.agent_id))}
    for agent in bind.execute(sa.select(agents.c.id, agents.c.tenant_id, agents.c.workspace_id)).mappings():
        if agent["id"] in existing:
            continue
        bind.execute(
            settings.insert().values(
                agent_id=agent["id"],
                tenant_id=agent["tenant_id"],
                workspace_id=agent["workspace_id"],
                purpose="support",
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "agent_purpose_settings" in tables:
        op.drop_table("agent_purpose_settings")
