"""Section 23: compatibility exports must work in either Python import order."""

from __future__ import annotations

import subprocess
import sys
from textwrap import dedent

import pytest


@pytest.mark.parametrize(
    "imports",
    [
        """
        from northstar_api.modules.workspace.branding import router as legacy_router
        from northstar_api.modules.branding import branding_router
        from northstar_api.modules.branding import brand_draft_router, brand_versions_router
        assert legacy_router is branding_router
        assert len(brand_draft_router.routes) == 3
        assert len(brand_versions_router.routes) == 2
        """,
        """
        from northstar_api.modules.branding import branding_router
        from northstar_api.modules.branding import brand_draft_router, brand_versions_router
        from northstar_api.modules.workspace.branding import router as legacy_router
        assert legacy_router is branding_router
        assert len(brand_draft_router.routes) == 3
        assert len(brand_versions_router.routes) == 2
        """,
    ],
)
def test_branding_imports_work_in_both_orders(imports: str) -> None:
    # Run in fresh interpreters: pytest's shared import cache cannot expose
    # a circular import that occurs only during initial package loading.
    result = subprocess.run(
        [sys.executable, "-c", dedent(imports)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
