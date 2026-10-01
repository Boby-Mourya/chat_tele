from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

_INDEX_NAME = "ix_outbox_webhook_pending_lookup"
_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "versions"
    / "0038_outbox_webhook_timing_index.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "migration_0038_outbox_webhook_timing_index",
        _MIGRATION_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _index_sql(connection: sa.Connection) -> str | None:
    return connection.scalar(
        sa.text(
            "SELECT sql FROM sqlite_master "
            "WHERE type = 'index' AND name = :index_name"
        ),
        {"index_name": _INDEX_NAME},
    )


def test_outbox_webhook_timing_index_migration_is_linear_idempotent_and_reversible() -> None:
    migration = _load_migration()
    assert migration.revision == "0038_outbox_webhook_timing_index"
    assert migration.down_revision == "0037_channel_delivery_attempts"

    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "CREATE TABLE outbox_events ("
                "id VARCHAR(36) PRIMARY KEY, "
                "tenant_id VARCHAR(36) NOT NULL, "
                "aggregate_type VARCHAR(80) NOT NULL, "
                "aggregate_id VARCHAR(80) NOT NULL, "
                "event_type VARCHAR(160) NOT NULL, "
                "occurred_at DATETIME NOT NULL"
                ")"
            )
        )
        migration.op = Operations(MigrationContext.configure(connection))

        migration.upgrade()
        created_sql = _index_sql(connection)
        assert created_sql is not None
        normalized_sql = " ".join(created_sql.lower().split())
        assert "tenant_id" in normalized_sql
        assert "aggregate_type" in normalized_sql
        assert "event_type" in normalized_sql
        assert "replace(aggregate_id, '-', '')" in normalized_sql
        assert "occurred_at" in normalized_sql

        migration.upgrade()
        index_count = connection.scalar(
            sa.text(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type = 'index' AND name = :index_name"
            ),
            {"index_name": _INDEX_NAME},
        )
        assert index_count == 1

        migration.downgrade()
        assert _index_sql(connection) is None

    engine.dispose()


def test_outbox_webhook_timing_index_migration_is_safe_when_table_is_absent() -> None:
    migration = _load_migration()
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        migration.downgrade()
        assert _index_sql(connection) is None
    engine.dispose()
