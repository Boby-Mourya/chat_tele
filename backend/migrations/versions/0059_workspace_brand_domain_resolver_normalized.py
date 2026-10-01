"""Prefer normalized workspace custom-domain records for public brand resolution.

Revision ID: 0059_workspace_brand_domain_resolver_normalized
Revises: 0058_workspace_branding_tables
"""

from __future__ import annotations

from alembic import op

revision = "0059_workspace_brand_domain_resolver_normalized"
down_revision = "0058_workspace_branding_tables"
branch_labels = None
depends_on = None


def _secure_function() -> None:
    op.execute("REVOKE ALL ON FUNCTION northstar_resolve_workspace_domain(text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION northstar_resolve_workspace_domain(text) TO northstar_app")


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
          WITH normalized_match AS (
            SELECT d.tenant_id, d.workspace_id, 0 AS priority
            FROM workspace_custom_domain AS d
            JOIN workspaces AS w
              ON w.id = d.workspace_id
             AND w.tenant_id = d.tenant_id
            WHERE w.status = 'active'
              AND d.status = 'active'
              AND lower(d.hostname) = lower(trim(trailing '.' from p_hostname))
            LIMIT 1
          ), legacy_match AS (
            SELECT w.tenant_id, w.id AS workspace_id, 1 AS priority
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
            LIMIT 1
          )
          SELECT match.tenant_id, match.workspace_id
          FROM (
            SELECT * FROM normalized_match
            UNION ALL
            SELECT * FROM legacy_match
          ) AS match
          ORDER BY match.priority
          LIMIT 1
        $$
        """
    )
    _secure_function()


def downgrade() -> None:
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
    _secure_function()
