"""Check the independently developed workspace/extraction revision junction."""
from __future__ import annotations

import ast
from pathlib import Path

from alembic.script.revision import Revision, RevisionMap

VERSIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def metadata(filename: str) -> dict[str, object]:
    values: dict[str, object] = {}
    for node in ast.parse((VERSIONS / filename).read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in {"revision", "down_revision"}:
                values[name] = ast.literal_eval(node.value)
    return values


def test_workspace_and_extraction_histories_have_a_common_successor() -> None:
    # The existing ancestors are outside this junction-specific regression test.
    root = "0043_knowledge_training"
    records = [Revision(root, None)]
    for filename in (
        "0044_workspace_onboarding.py",
        "0044_hybrid_extraction_review.py",
        "0044_merge_workspace_extraction.py",
    ):
        values = metadata(filename)
        records.append(Revision(values["revision"], values["down_revision"]))
    graph = RevisionMap(lambda: iter(records))
    assert graph.heads == ("0044_merge_workspace_extraction",)
    merged = graph.get_revision("0044_merge_workspace_extraction")
    assert merged is not None
    assert set(merged._all_down_revisions) == {
        "0044_workspace_onboarding", "0044_hybrid_extraction_review",
    }


def test_merge_revision_does_not_modify_customer_data() -> None:
    tree = ast.parse((VERSIONS / "0044_merge_workspace_extraction.py").read_text(encoding="utf-8"))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert set(functions) == {"upgrade", "downgrade"}
    assert all(len(node.body) == 1 and isinstance(node.body[0], ast.Pass) for node in functions.values())
