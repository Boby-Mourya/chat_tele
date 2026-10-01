"""Record starter-template lineage and idempotent clone receipts; preserve existing agents."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0045_starter_template_clones"
down_revision = "0044_merge_workspace_extraction"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "starter_template_clones",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("catalog_id", sa.String(100), nullable=False),
        sa.Column("catalog_version", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("recipe_digest", sa.String(64), nullable=False),
        sa.Column("agent_id", sa.Uuid(), sa.ForeignKey("agents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "workspace_id", "actor_id", "request_id", name="uq_starter_clone_request"),
        sa.CheckConstraint("catalog_version >= 1", name=op.f("ck_starter_template_clones_starter_clone_catalog_version")),
    )
    op.create_index("ix_starter_clones_scope", "starter_template_clones", ["tenant_id", "workspace_id", "created_at"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE starter_template_clones ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE starter_template_clones FORCE ROW LEVEL SECURITY")
        op.execute("""
            CREATE POLICY starter_clone_scope ON starter_template_clones
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                AND EXISTS (SELECT 1 FROM workspaces w
                            WHERE w.id = starter_template_clones.workspace_id AND w.tenant_id = starter_template_clones.tenant_id)
                AND (agent_id IS NULL OR EXISTS (SELECT 1 FROM agents a
                     WHERE a.id = starter_template_clones.agent_id AND a.tenant_id = starter_template_clones.tenant_id
                     AND a.workspace_id = starter_template_clones.workspace_id))
            )
        """)
        op.execute("GRANT SELECT, INSERT ON starter_template_clones TO northstar_app")
        op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON starter_template_clones TO northstar_service")


def downgrade() -> None:
    # Rollback removes lineage/receipts, not customer agents. Disable clone writes
    # before downgrade: old idempotency keys cannot remain safe after receipt loss.
    op.drop_index("ix_starter_clones_scope", table_name="starter_template_clones")
    op.drop_table("starter_template_clones")
