from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_COMPOSE_OVERRIDE = _ROOT / "compose.override.yaml"
_KUBERNETES_MIGRATION = _ROOT / "kubernetes" / "base" / "migration.yaml"


def test_default_compose_migration_override_upgrades_all_heads() -> None:
    content = _COMPOSE_OVERRIDE.read_text(encoding="utf-8")
    start = content.index("  migrate:\n")
    end = content.index("\n  notification-consumer:\n", start)
    migrate_block = content[start:end]

    assert 'command: ["alembic", "upgrade", "heads"]' in migrate_block
    assert 'command: ["alembic", "upgrade", "head"]' not in migrate_block


def test_kubernetes_migration_job_upgrades_all_heads() -> None:
    content = _KUBERNETES_MIGRATION.read_text(encoding="utf-8")

    assert "command: [alembic, upgrade, heads]" in content
    assert "command: [alembic, upgrade, head]" not in content
