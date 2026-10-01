"""Section 23: staged module imports must not cycle through legacy routers."""

from __future__ import annotations

import subprocess
import sys
from textwrap import dedent
from types import SimpleNamespace
from uuid import uuid4

import pytest

from northstar_api.modules.workspace import store


@pytest.mark.parametrize(
    "imports",
    [
        """
        from northstar_api.modules.workspace.store import load_workspace
        from northstar_api.modules.workspace.router import router as settings_router
        from northstar_api.routers import api_router
        assert callable(load_workspace)
        assert any(route.path == "/workspace/settings/branding" for route in api_router.routes)
        """,
        """
        from northstar_api.modules.workspace.router import router as settings_router
        from northstar_api.routers import api_router
        from northstar_api.modules.workspace.store import load_workspace
        assert callable(load_workspace)
        assert any(route.path == "/workspace/settings/branding" for route in api_router.routes)
        """,
        """
        from northstar_api.routers import api_router
        from northstar_api.modules.workspace.router import router as settings_router
        from northstar_api.modules.workspace.store import load_workspace
        assert callable(load_workspace)
        assert any(route.path == "/workspace/settings/branding" for route in api_router.routes)
        """,
    ],
)
def test_workspace_routes_import_in_any_order(imports: str) -> None:
    # Each case must begin with an empty module cache, not pytest's cache.
    result = subprocess.run(
        [sys.executable, "-c", dedent(imports)],
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.asyncio
async def test_workspace_loader_still_uses_existing_scoped_legacy_loader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from northstar_api.routers import workspace as legacy_workspace

    tenant_id, workspace_id, user_id = uuid4(), uuid4(), uuid4()
    principal = SimpleNamespace(tenant_id=tenant_id, workspace_id=workspace_id, user_id=user_id)
    tenant, workspace, session = object(), object(), object()
    calls: list[tuple[object, ...]] = []

    async def original_scoped_loader(*args: object) -> tuple[object, object, None, None]:
        calls.append(args)
        return tenant, workspace, None, None

    monkeypatch.setattr(legacy_workspace, "_load_workspace", original_scoped_loader)
    resolved = await store.load_workspace(principal, session)  # type: ignore[arg-type]
    assert resolved == (tenant, workspace)
    assert calls == [(tenant_id, workspace_id, user_id, session)]
