"""Separate SaaS tenants from operational workspaces.

Revision ID: 0011_tenant_workspaces
Revises: 0010_crm_verification, 0005_help_center
"""

from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0011_tenant_workspaces"
down_revision = ("0010_crm_verification", "0005_help_center")
branch_labels = None
depends_on = None

WORKSPACE_TABLES = (
    "agents",
    "knowledge_sources",
    "document_chunks",
    "knowledge_facts",
    "ingestion_jobs",
    "conversations",
    "messages",
    "message_citations",
    "message_feedback",
    "leads",
    "integration_connections",
    "whatsapp_connections",
    "whatsapp_inbound_messages",
    "whatsapp_outbound_deliveries",
    "agent_health_daily",
    "outbox_events",
)


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _unique_for(table: str, columns: set[str]) -> str | None:
    for item in sa.inspect(op.get_bind()).get_unique_constraints(table):
        if set(item.get("column_names") or []) == columns:
            return item.get("name")
    return None


def _workspace_role(role: Any) -> str:
    value = getattr(role, "value", role)
    return {
        "owner": "workspace_admin",
        "admin": "workspace_admin",
        "member": "operator",
        "analyst": "analyst",
    }.get(str(value), "viewer")


def upgrade() -> None:
    bind = op.get_bind()
    tables = _tables()
    if "workspaces" not in tables:
        op.create_table(
            "workspaces",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("name", sa.String(160), nullable=False),
            sa.Column("slug", sa.String(80), nullable=False),
            sa.Column("status", sa.String(24), nullable=False, server_default="active"),
            sa.Column("timezone", sa.String(80), nullable=False, server_default="Asia/Calcutta"),
            sa.Column("default_language", sa.String(60), nullable=False, server_default="English"),
            sa.Column("date_format", sa.String(24), nullable=False, server_default="DD/MM/YYYY"),
            sa.Column("settings_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("branding_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_by", sa.Uuid()),
            sa.Column("archived_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tenant_id", "slug", name="uq_workspaces_tenant_slug"),
        )
        op.create_index("ix_workspaces_tenant_id", "workspaces", ["tenant_id"])
        op.create_index("ix_workspaces_tenant_status", "workspaces", ["tenant_id", "status"])

    workspace_table = sa.table(
        "workspaces",
        sa.column("id", sa.Uuid()),
        sa.column("tenant_id", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column("slug", sa.String()),
        sa.column("status", sa.String()),
        sa.column("timezone", sa.String()),
        sa.column("default_language", sa.String()),
        sa.column("date_format", sa.String()),
        sa.column("settings_json", sa.JSON()),
        sa.column("branding_json", sa.JSON()),
    )
    tenant_rows = bind.execute(sa.text("SELECT id, name, settings_json FROM tenants")).mappings().all()
    workspace_ids: dict[Any, uuid.UUID] = {}
    for tenant in tenant_rows:
        existing = bind.execute(
            sa.text("SELECT id FROM workspaces WHERE tenant_id = :tenant_id ORDER BY created_at LIMIT 1"),
            {"tenant_id": tenant["id"]},
        ).scalar_one_or_none()
        if existing:
            workspace_ids[tenant["id"]] = uuid.UUID(str(existing))
            continue
        settings = tenant.get("settings_json") or {}
        preferences = settings.get("preferences") or {}
        workspace_id = uuid.uuid4()
        workspace_ids[tenant["id"]] = workspace_id
        bind.execute(
            workspace_table.insert().values(
                id=workspace_id,
                tenant_id=tenant["id"],
                name=tenant["name"],
                slug="default",
                status="active",
                timezone=preferences.get("timezone", "Asia/Calcutta"),
                default_language=preferences.get("defaultLanguage", "English"),
                date_format=preferences.get("dateFormat", "DD/MM/YYYY"),
                settings_json={"preferences": preferences} if preferences else {},
                branding_json=settings.get("whiteLabel") or {},
            )
        )

    tables = _tables()
    if "workspace_memberships" not in tables:
        op.create_table(
            "workspace_memberships",
            sa.Column("workspace_id", sa.Uuid(), nullable=False),
            sa.Column("user_id", sa.Uuid(), nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("role", sa.String(32), nullable=False, server_default="viewer"),
            sa.Column("all_agents_access", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("workspace_id", "user_id"),
            sa.UniqueConstraint(
                "workspace_id", "user_id", name="uq_workspace_memberships_workspace_user"
            ),
        )
        op.create_index(
            "ix_workspace_memberships_tenant_user",
            "workspace_memberships",
            ["tenant_id", "user_id"],
        )
    membership_table = sa.table(
        "workspace_memberships",
        sa.column("workspace_id", sa.Uuid()),
        sa.column("user_id", sa.Uuid()),
        sa.column("tenant_id", sa.Uuid()),
        sa.column("role", sa.String()),
        sa.column("all_agents_access", sa.Boolean()),
    )
    memberships = bind.execute(
        sa.text("SELECT tenant_id, user_id, role FROM tenant_memberships")
    ).mappings()
    for membership in memberships:
        workspace_id = workspace_ids.get(membership["tenant_id"])
        if not workspace_id:
            continue
        exists = bind.execute(
            sa.text(
                "SELECT 1 FROM workspace_memberships "
                "WHERE workspace_id = :workspace_id AND user_id = :user_id"
            ),
            {"workspace_id": workspace_id, "user_id": membership["user_id"]},
        ).scalar_one_or_none()
        if not exists:
            bind.execute(
                membership_table.insert().values(
                    workspace_id=workspace_id,
                    user_id=membership["user_id"],
                    tenant_id=membership["tenant_id"],
                    role=_workspace_role(membership["role"]),
                    all_agents_access=True,
                )
            )

    if "workspace_member_agent_access" not in tables:
        op.create_table(
            "workspace_member_agent_access",
            sa.Column("workspace_id", sa.Uuid(), nullable=False),
            sa.Column("user_id", sa.Uuid(), nullable=False),
            sa.Column("agent_id", sa.Uuid(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("workspace_id", "user_id", "agent_id"),
        )
        op.create_index(
            "ix_workspace_agent_access_user",
            "workspace_member_agent_access",
            ["workspace_id", "user_id"],
        )

    for table in WORKSPACE_TABLES:
        if table not in _tables():
            continue
        if "workspace_id" not in _columns(table):
            op.add_column(table, sa.Column("workspace_id", sa.Uuid(), nullable=True))
        op.execute(
            sa.text(
                f'UPDATE "{table}" SET workspace_id = '
                "(SELECT id FROM workspaces WHERE workspaces.tenant_id = "
                f'"{table}".tenant_id ORDER BY created_at LIMIT 1) '
                "WHERE workspace_id IS NULL"
            )
        )
        if table != "outbox_events":
            op.alter_column(table, "workspace_id", nullable=False)
        fk_names = {
            fk.get("name") for fk in sa.inspect(bind).get_foreign_keys(table)
            if fk.get("constrained_columns") == ["workspace_id"]
        }
        if not any(fk_names):
            op.create_foreign_key(
                f"fk_{table}_workspace_id_workspaces",
                table,
                "workspaces",
                ["workspace_id"],
                ["id"],
                ondelete="CASCADE",
            )
        index_name = f"ix_{table}_workspace_id"
        existing_indexes = {item["name"] for item in sa.inspect(bind).get_indexes(table)}
        if index_name not in existing_indexes:
            op.create_index(index_name, table, ["workspace_id"])

    replacements = (
        ("agents", {"tenant_id", "name"}, "uq_agents_workspace_name", ["workspace_id", "name"]),
        (
            "integration_connections",
            {"tenant_id", "integration_id"},
            "uq_integration_connections_workspace_integration",
            ["workspace_id", "integration_id"],
        ),
        (
            "whatsapp_connections",
            {"tenant_id", "agent_id"},
            "uq_whatsapp_connections_workspace_agent",
            ["workspace_id", "agent_id"],
        ),
        (
            "agent_health_daily",
            {"tenant_id", "agent_id", "day"},
            "uq_agent_health_workspace_agent_day",
            ["workspace_id", "agent_id", "day"],
        ),
    )
    for table, old_columns, new_name, new_columns in replacements:
        old_name = _unique_for(table, old_columns)
        if old_name:
            op.drop_constraint(old_name, table, type_="unique")
        if not _unique_for(table, set(new_columns)):
            op.create_unique_constraint(new_name, table, new_columns)

    if bind.dialect.name == "postgresql":
        for table in ("workspaces", "workspace_memberships", "workspace_member_agent_access"):
            op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{table}" TO northstar_app')


def downgrade() -> None:
    for table in reversed(WORKSPACE_TABLES):
        if table in _tables() and "workspace_id" in _columns(table):
            op.drop_column(table, "workspace_id")
    for table in ("workspace_member_agent_access", "workspace_memberships", "workspaces"):
        if table in _tables():
            op.drop_table(table)
