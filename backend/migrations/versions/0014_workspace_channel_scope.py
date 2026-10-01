"""Add authoritative Agent channel and workspace channel ownership.

Revision ID: 0014_workspace_channel_scope
Revises: 0013_workspace_crm_scope
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014_workspace_channel_scope"
down_revision = "0013_workspace_crm_scope"
branch_labels = None
depends_on = None

SUPPORTED = {
    "website",
    "whatsapp",
    "telegram",
    "instagram",
    "facebook",
    "facebook_messenger",
    "slack",
    "teams",
    "api",
    "notion",
    "zapier",
}


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "agent_channel_bindings" not in tables:
        op.create_table(
            "agent_channel_bindings",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("workspace_id", sa.Uuid(), nullable=False),
            sa.Column("agent_id", sa.Uuid(), nullable=False),
            sa.Column("channel_type", sa.String(length=60), nullable=False, server_default="website"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("agent_id", name="uq_agent_channel_binding_agent"),
        )
        op.create_index(
            "ix_agent_channel_binding_scope",
            "agent_channel_bindings",
            ["tenant_id", "workspace_id", "channel_type"],
        )
        op.create_index("ix_agent_channel_bindings_tenant_id", "agent_channel_bindings", ["tenant_id"])
        op.create_index("ix_agent_channel_bindings_workspace_id", "agent_channel_bindings", ["workspace_id"])
        op.create_index("ix_agent_channel_bindings_agent_id", "agent_channel_bindings", ["agent_id"])

    if "workspace_channel_connections" not in tables:
        op.create_table(
            "workspace_channel_connections",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("workspace_id", sa.Uuid(), nullable=False),
            sa.Column("agent_id", sa.Uuid(), nullable=True),
            sa.Column("connection_id", sa.Uuid(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["connection_id"], ["channel_connections.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("connection_id", name="uq_workspace_channel_connection"),
        )
        op.create_index(
            "ix_workspace_channel_connection_scope",
            "workspace_channel_connections",
            ["tenant_id", "workspace_id", "agent_id"],
        )
        op.create_index(
            "ix_workspace_channel_connections_tenant_id", "workspace_channel_connections", ["tenant_id"]
        )
        op.create_index(
            "ix_workspace_channel_connections_workspace_id", "workspace_channel_connections", ["workspace_id"]
        )
        op.create_index(
            "ix_workspace_channel_connections_agent_id", "workspace_channel_connections", ["agent_id"]
        )
        op.create_index(
            "ix_workspace_channel_connections_connection_id", "workspace_channel_connections", ["connection_id"]
        )

    meta = sa.MetaData()
    agents = sa.Table("agents", meta, autoload_with=bind)
    bindings = sa.Table("agent_channel_bindings", meta, autoload_with=bind)
    existing_agents = {row[0] for row in bind.execute(sa.select(bindings.c.agent_id))}
    for agent in bind.execute(
        sa.select(agents.c.id, agents.c.tenant_id, agents.c.workspace_id, agents.c.appearance)
    ).mappings():
        if agent["id"] in existing_agents:
            continue
        appearance = agent["appearance"] if isinstance(agent["appearance"], dict) else {}
        raw = str((appearance or {}).get("deploymentChannel") or "website").lower().strip()
        channel = raw if raw in SUPPORTED else "website"
        bind.execute(
            bindings.insert().values(
                id=agent["id"],
                tenant_id=agent["tenant_id"],
                workspace_id=agent["workspace_id"],
                agent_id=agent["id"],
                channel_type=channel,
            )
        )

    if "channel_connections" in tables:
        workspaces = sa.Table("workspaces", meta, autoload_with=bind)
        connections = sa.Table("channel_connections", meta, autoload_with=bind)
        scopes = sa.Table("workspace_channel_connections", meta, autoload_with=bind)
        existing_connections = {row[0] for row in bind.execute(sa.select(scopes.c.connection_id))}
        for connection in bind.execute(
            sa.select(connections.c.id, connections.c.tenant_id)
        ).mappings():
            if connection["id"] in existing_connections:
                continue
            workspace_id = bind.execute(
                sa.select(workspaces.c.id)
                .where(workspaces.c.tenant_id == connection["tenant_id"])
                .order_by(workspaces.c.created_at, workspaces.c.id)
                .limit(1)
            ).scalar_one_or_none()
            if workspace_id is not None:
                bind.execute(
                    scopes.insert().values(
                        id=connection["id"],
                        tenant_id=connection["tenant_id"],
                        workspace_id=workspace_id,
                        agent_id=None,
                        connection_id=connection["id"],
                    )
                )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "workspace_channel_connections" in tables:
        op.drop_table("workspace_channel_connections")
    if "agent_channel_bindings" in tables:
        op.drop_table("agent_channel_bindings")
