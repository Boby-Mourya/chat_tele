from __future__ import annotations

import re
from pathlib import Path

_WORKFLOW_PATH = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"


def _migration_head_gate() -> str:
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")
    start = workflow.index("      - name: Verify migration heads")
    end = workflow.index("      - name: Verify CRM API and migrated verification columns", start)
    return workflow[start:end]


def test_ci_compares_database_and_repository_alembic_head_sets() -> None:
    gate = _migration_head_gate()

    assert "docker compose exec -T api alembic current" in gate
    assert "docker compose exec -T api alembic heads" in gate
    assert 'if [ -z "$expected_heads" ]' in gate
    assert 'if [ "$current_heads" != "$expected_heads" ]' in gate
    assert "Database migration heads do not match the repository heads" in gate


def test_ci_migration_gate_does_not_hardcode_a_revision() -> None:
    gate = _migration_head_gate()

    assert "grep -q" not in gate
    assert re.search(r"\b00\d{2}_[a-z0-9_]+\b", gate) is None
