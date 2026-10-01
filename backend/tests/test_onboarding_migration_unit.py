import importlib.util
import json
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

PATH = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "0044_workspace_onboarding.py"
spec = importlib.util.spec_from_file_location("workspace_onboarding_migration", PATH)
assert spec is not None and spec.loader is not None
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


def database(plan="starter"):
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("PRAGMA foreign_keys=ON"))
        connection.execute(sa.text("CREATE TABLE tenants(id CHAR(32) PRIMARY KEY, name VARCHAR(160), plan VARCHAR(40))"))
        connection.execute(sa.text("CREATE TABLE users(id CHAR(32) PRIMARY KEY)"))
        connection.execute(sa.text("CREATE TABLE tenant_subscriptions(tenant_id CHAR(32), plan VARCHAR(40))"))
        tenant_id = uuid4().hex
        connection.execute(sa.text("INSERT INTO tenants VALUES(:id, 'Existing Academy', :plan)"), {"id": tenant_id, "plan": plan})
        connection.execute(sa.text("INSERT INTO tenant_subscriptions VALUES(:id, :plan)"), {"id": tenant_id, "plan": plan})
    return engine, tenant_id


def test_upgrade_preserves_existing_access_and_does_not_invent_profile(monkeypatch):
    monkeypatch.delenv("NORTHSTAR_LEGACY_PLAN_ALIASES", raising=False)
    engine, tenant_id = database()
    with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        migration.upgrade()
        row = connection.execute(sa.text("SELECT * FROM organization_setups")).mappings().one()
        assert row["tenant_id"] == tenant_id
        assert row["required"] == 0 and row["profile_complete"] == 0
        assert json.loads(row["profile_json"]) == {"displayName": "Existing Academy"}
        assert len(json.loads(row["catalog_grants"])) == 3
        assert row["branding_choice"] == "unseen" and row["revision"] == 0
        with pytest.raises(sa.exc.IntegrityError):
            connection.execute(sa.text("UPDATE organization_setups SET revision=-1"))
        migration.downgrade()
        assert "organization_setups" not in sa.inspect(connection).get_table_names()
        assert connection.execute(sa.text("SELECT count(*) FROM tenants")).scalar_one() == 1


def test_unknown_plan_blocks_migration_before_writes(monkeypatch):
    monkeypatch.delenv("NORTHSTAR_LEGACY_PLAN_ALIASES", raising=False)
    engine, _ = database("customer-contract")
    with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        with pytest.raises(RuntimeError, match="Map existing legacy plans"):
            migration.upgrade()
        assert "organization_setups" not in sa.inspect(connection).get_table_names()
        assert connection.execute(sa.text("SELECT plan FROM tenants")).scalar_one() == "customer-contract"


def test_approved_mapping_applies_to_tenant_and_subscription(monkeypatch):
    monkeypatch.setenv("NORTHSTAR_LEGACY_PLAN_ALIASES", '{"customer-contract":"business"}')
    engine, _ = database("customer-contract")
    with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        migration.upgrade()
        assert connection.execute(sa.text("SELECT plan FROM tenants")).scalar_one() == "business"
        assert connection.execute(sa.text("SELECT plan FROM tenant_subscriptions")).scalar_one() == "business"


@pytest.mark.parametrize("value", ["[]", '{"starter":"enterprise"}', '{"contract":"typo"}'])
def test_invalid_mapping_rejected(monkeypatch, value):
    monkeypatch.setenv("NORTHSTAR_LEGACY_PLAN_ALIASES", value)
    engine, _ = database()
    with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        with pytest.raises(RuntimeError):
            migration.upgrade()
