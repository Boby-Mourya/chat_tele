"""Add a narrowly scoped resolver for active workspace custom domains.

Revision ID: 0055_workspace_brand_domain_resolver
Revises: 0054_knowledge_audit_tables
"""

from __future__ import annotations

from alembic import op

revision = "0055_workspace_brand_domain_resolver"
down_revision = "0054_knowledge_audit_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(
        """
        CREATE OR REPLACE FUNCTION northstar_resolve_workspace_domain(p_hostname text)
        RETURNS TABLE(tenant_id uuid, workspace_id uuid)
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = public
        AS $$
          SELECT w.tenant_id, w.id
          FROM workspaces AS w
          CROSS JOIN LATERAL jsonb_array_elements(
            COALESCE(
              w.settings_json::jsonb #> '{workspaceSettingsV2,domains,domains}',
              '[]'::jsonb
            )
          ) AS domain_record
          WHERE w.status = 'active'
            AND lower(domain_record ->> 'hostname') = lower(trim(trailing '.' from p_hostname))
            AND domain_record ->> 'status' = 'active'
          ORDER BY w.created_at, w.id
          LIMIT 1
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION northstar_resolve_workspace_domain(text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION northstar_resolve_workspace_domain(text) TO northstar_app")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP FUNCTION IF EXISTS northstar_resolve_workspace_domain(text)")
