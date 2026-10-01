"""Verify the duplicate knowledge-audit revision preserves the 0043 schema."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa

MIGRATION = Path(__file__).parents[1] / "migrations/versions/0054_knowledge_audit_tables.py"


def _migration():
    spec = importlib.util.spec_from_file_location("knowledge_audit_migration", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_and_downgrade_preserve_knowledge_tables_and_data():
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    snapshots = sa.Table(
        "knowledge_snapshots",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("manifest", sa.JSON, nullable=False),
    )
    audits = sa.Table(
        "knowledge_answer_audits",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("details", sa.JSON, nullable=False),
    )
    with engine.begin() as connection:
        metadata.create_all(connection)
        connection.execute(snapshots.insert().values(id=1, revision=1, manifest={"sources": []}))
        connection.execute(audits.insert().values(id=1, details={"mode": "approved_knowledge_only"}))

        migration = _migration()
        migration.upgrade()
        assert connection.scalar(sa.select(sa.func.count()).select_from(snapshots)) == 1
        assert connection.scalar(sa.select(sa.func.count()).select_from(audits)) == 1

        migration.downgrade()
        assert set(sa.inspect(connection).get_table_names()) == {
            "knowledge_snapshots",
            "knowledge_answer_audits",
        }
    engine.dispose()
