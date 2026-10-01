"""Scope CRM connections and routes to operational workspaces.

Revision ID: 0013_workspace_crm_scope
Revises: 0012_conversation_resolution_leads
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013_workspace_crm_scope"
down_revision = "0012_conversation_resolution_leads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "workspace_crm_connections" not in tables:
        op.create_table(
            "workspace_crm_connections",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("workspace_id", sa.Uuid(), nullable=False),
            sa.Column("connection_id", sa.Uuid(), nullable=False),
            sa.Column("auto_sync_new_leads", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("auto_sync_updates", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["connection_id"], ["crm_connections.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("connection_id", name="uq_workspace_crm_connection"),
            sa.UniqueConstraint("workspace_id", "connection_id", name="uq_workspace_crm_connection_scope"),
        )
        op.create_index(
            "ix_workspace_crm_connections_scope",
            "workspace_crm_connections",
            ["tenant_id", "workspace_id"],
        )
        op.create_index(
            "ix_workspace_crm_connections_tenant_id", "workspace_crm_connections", ["tenant_id"]
        )
        op.create_index(
            "ix_workspace_crm_connections_workspace_id", "workspace_crm_connections", ["workspace_id"]
        )
        op.create_index(
            "ix_workspace_crm_connections_connection_id", "workspace_crm_connections", ["connection_id"]
        )

    if "workspace_crm_routes" not in tables:
        op.create_table(
            "workspace_crm_routes",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("workspace_id", sa.Uuid(), nullable=False),
            sa.Column("route_id", sa.Uuid(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["route_id"], ["crm_routes.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("route_id", name="uq_workspace_crm_route"),
            sa.UniqueConstraint("workspace_id", "route_id", name="uq_workspace_crm_route_scope"),
        )
        op.create_index(
            "ix_workspace_crm_routes_scope", "workspace_crm_routes", ["tenant_id", "workspace_id"]
        )
        op.create_index("ix_workspace_crm_routes_tenant_id", "workspace_crm_routes", ["tenant_id"])
        op.create_index("ix_workspace_crm_routes_workspace_id", "workspace_crm_routes", ["workspace_id"])
        op.create_index("ix_workspace_crm_routes_route_id", "workspace_crm_routes", ["route_id"])

    # Preserve all legacy CRM configuration by assigning each existing record to
    # its tenant's earliest workspace (the workspace created by migration 0011).
    meta = sa.MetaData()
    workspaces = sa.Table("workspaces", meta, autoload_with=bind)
    if "crm_connections" in tables:
        connections = sa.Table("crm_connections", meta, autoload_with=bind)
        connection_scope = sa.Table("workspace_crm_connections", meta, autoload_with=bind)
        existing = {row[0] for row in bind.execute(sa.select(connection_scope.c.connection_id))}
        for connection in bind.execute(sa.select(connections.c.id, connections.c.tenant_id)).mappings():
            if connection["id"] in existing:
                continue
            workspace_id = bind.execute(
                sa.select(workspaces.c.id)
                .where(workspaces.c.tenant_id == connection["tenant_id"])
                .order_by(workspaces.c.created_at, workspaces.c.id)
                .limit(1)
            ).scalar_one_or_none()
            if workspace_id is not None:
                bind.execute(
                    connection_scope.insert().values(
                        id=connection["id"],
                        tenant_id=connection["tenant_id"],
                        workspace_id=workspace_id,
                        connection_id=connection["id"],
                        auto_sync_new_leads=True,
                        auto_sync_updates=True,
                    )
                )

    if "crm_routes" in tables:
        routes = sa.Table("crm_routes", meta, autoload_with=bind)
        route_scope = sa.Table("workspace_crm_routes", meta, autoload_with=bind)
        existing = {row[0] for row in bind.execute(sa.select(route_scope.c.route_id))}
        for route in bind.execute(sa.select(routes.c.id, routes.c.tenant_id)).mappings():
            if route["id"] in existing:
                continue
            workspace_id = bind.execute(
                sa.select(workspaces.c.id)
                .where(workspaces.c.tenant_id == route["tenant_id"])
                .order_by(workspaces.c.created_at, workspaces.c.id)
                .limit(1)
            ).scalar_one_or_none()
            if workspace_id is not None:
                bind.execute(
                    route_scope.insert().values(
                        id=route["id"],
                        tenant_id=route["tenant_id"],
                        workspace_id=workspace_id,
                        route_id=route["id"],
                    )
                )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "workspace_crm_routes" in tables:
        op.drop_table("workspace_crm_routes")
    if "workspace_crm_connections" in tables:
        op.drop_table("workspace_crm_connections")
