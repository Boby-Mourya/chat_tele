"""Organization onboarding and explicit legacy-plan migration.

Existing organizations retain their profile-completion grace. Unknown commercial
plans require an operator-supplied mapping; this migration never guesses a tier.
"""
from __future__ import annotations

import json
import os
from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0044_workspace_onboarding"
down_revision = "0043_knowledge_training"
branch_labels = None
depends_on = None

KNOWN_PLANS = {"free", "starter", "professional", "business", "enterprise"}
CATALOG_IDS = ["getting-started", "support-template", "education-boundaries"]


def upgrade() -> None:
    bind = op.get_bind()
    aliases = json.loads(os.environ.get("NORTHSTAR_LEGACY_PLAN_ALIASES", "{}"))
    if not isinstance(aliases, dict) or any(
        not isinstance(old, str) or old.strip().lower() in KNOWN_PLANS
        or not isinstance(new, str) or new.strip().lower() not in KNOWN_PLANS
        for old, new in aliases.items()
    ):
        raise RuntimeError("NORTHSTAR_LEGACY_PLAN_ALIASES must map unknown legacy plans to explicit catalog plans")
    aliases = {old.strip().lower(): new.strip().lower() for old, new in aliases.items()}
    observed = set(bind.execute(sa.text(
        "SELECT plan FROM tenants UNION SELECT plan FROM tenant_subscriptions"
    )).scalars())
    unknown = {str(value).strip().lower() for value in observed} - KNOWN_PLANS - aliases.keys()
    if unknown:
        raise RuntimeError("Map existing legacy plans before migrating: " + ", ".join(sorted(unknown)))
    for old in observed:
        normalized = str(old).strip().lower()
        mapped = aliases.get(normalized, normalized)
        bind.execute(sa.text("UPDATE tenants SET plan=:new WHERE plan=:old"), {"new": mapped, "old": old})
        bind.execute(sa.text("UPDATE tenant_subscriptions SET plan=:new WHERE plan=:old"), {"new": mapped, "old": old})

    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    table = op.create_table(
        "organization_setups",
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("profile_json", json_type, nullable=False),
        sa.Column("draft_json", json_type, nullable=False),
        sa.Column("profile_complete", sa.Boolean(), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("branding_choice", sa.String(24), nullable=False),
        sa.Column("choice_actor_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("choice_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("catalog_grants", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("revision >= 0", name="ck_organization_setups_setup_revision_nonnegative"),
        sa.CheckConstraint("branding_choice IN ('unseen', 'customize', 'keep_default', 'deferred')", name="ck_organization_setups_setup_brand_choice"),
    )
    for tenant_id, name in bind.execute(sa.text("SELECT id, name FROM tenants")):
        bind.execute(table.insert().values(
            tenant_id=UUID(str(tenant_id)), profile_json={"displayName": name},
            draft_json={"displayName": name, "workspaceName": name},
            profile_complete=False, required=False, revision=0, branding_choice="unseen",
            catalog_grants=CATALOG_IDS,
        ))
    if bind.dialect.name == "postgresql":
        op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON organization_setups TO northstar_app, northstar_service")
        op.execute("ALTER TABLE organization_setups ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE organization_setups FORCE ROW LEVEL SECURITY")
        op.execute("CREATE POLICY tenant_isolation ON organization_setups USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)")


def downgrade() -> None:
    op.drop_table("organization_setups")
