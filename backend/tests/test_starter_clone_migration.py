import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

PATH = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "0045_starter_template_clones.py"
spec = importlib.util.spec_from_file_location("starter_clone_migration", PATH)
assert spec and spec.loader
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


@pytest.fixture
def database():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(sa.text("PRAGMA foreign_keys=ON"))
        for name in ("tenants", "workspaces", "users", "agents"):
            conn.execute(sa.text(f"CREATE TABLE {name} (id CHAR(32) PRIMARY KEY)"))
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
    yield engine
    engine.dispose()


def seed(conn):
    result = {key: uuid4().hex for key in ("tenant_id", "workspace_id", "actor_id", "agent_id")}
    for key, table in (("tenant_id", "tenants"), ("workspace_id", "workspaces"), ("actor_id", "users"), ("agent_id", "agents")):
        conn.execute(sa.text(f"INSERT INTO {table} (id) VALUES (:id)"), {"id": result[key]})
    return {"id": uuid4().hex, **result, "request_id": uuid4().hex,
            "catalog_id": "support-template", "catalog_version": 1, "fingerprint": "a" * 64,
            "recipe_digest": "b" * 64, "name": "Sample copy"}


def insert(conn, values):
    conn.execute(sa.text("INSERT INTO starter_template_clones (" + ",".join(values) + ") VALUES ("
                         + ",".join(":" + field for field in values) + ")"), values)


def test_migration_descends_from_the_existing_junction():
    assert migration.down_revision == "0044_merge_workspace_extraction"


def test_scoped_idempotency_constraint(database):
    with database.begin() as conn:
        values = seed(conn)
        insert(conn, values)
        with pytest.raises(sa.exc.IntegrityError):
            insert(conn, {**values, "id": uuid4().hex})
        other = seed(conn)
        insert(conn, {**other, "request_id": values["request_id"]})
        assert conn.scalar(sa.text("SELECT count(*) FROM starter_template_clones")) == 2


@pytest.mark.parametrize("version", [0, -1])
def test_invalid_version_rejected(database, version):
    with database.begin() as conn:
        values = seed(conn)
        with pytest.raises(sa.exc.IntegrityError):
            insert(conn, {**values, "catalog_version": version})


def test_agent_deletion_retains_a_receipt_instead_of_enabling_replay(database):
    with database.begin() as conn:
        values = seed(conn); insert(conn, values)
        conn.execute(sa.text("DELETE FROM agents WHERE id=:id"), {"id": values["agent_id"]})
        assert conn.scalar(sa.text("SELECT count(*) FROM starter_template_clones")) == 1
        assert conn.scalar(sa.text("SELECT agent_id FROM starter_template_clones")) is None


def test_downgrade_does_not_delete_customer_agent(database):
    with database.begin() as conn:
        values = seed(conn); insert(conn, values)
        with Operations.context(MigrationContext.configure(conn)):
            migration.downgrade()
        assert "starter_template_clones" not in sa.inspect(conn).get_table_names()
        assert conn.scalar(sa.text("SELECT count(*) FROM agents")) == 1


def test_workspace_removal_cleans_up_its_receipts(database):
    with database.begin() as conn:
        values = seed(conn); insert(conn, values)
        conn.execute(sa.text("DELETE FROM workspaces WHERE id=:id"), {"id": values["workspace_id"]})
        assert conn.scalar(sa.text("SELECT count(*) FROM starter_template_clones")) == 0
