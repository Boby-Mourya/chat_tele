"""Section 23: model boundaries must not depend on who imports them first."""

from __future__ import annotations

import subprocess
import sys
from textwrap import dedent

import pytest


@pytest.mark.parametrize(
    "imports",
    [
        """
        from northstar_api.modules.workspace.models import Workspace, WorkspaceInvitation
        from northstar_api.models import Workspace as LegacyWorkspace
        from northstar_api.workspace_invitations import WorkspaceInvitation as LegacyInvitation
        assert Workspace is LegacyWorkspace
        assert WorkspaceInvitation is LegacyInvitation
        """,
        """
        from northstar_api.workspace_invitations import WorkspaceInvitation as LegacyInvitation
        from northstar_api.models import Workspace as LegacyWorkspace
        from northstar_api.modules.workspace.models import Workspace, WorkspaceInvitation
        assert Workspace is LegacyWorkspace
        assert WorkspaceInvitation is LegacyInvitation
        """,
        """
        from northstar_api.routers import api_router
        from northstar_api.modules.workspace.models import Workspace, WorkspaceInvitation
        from northstar_api.models import Workspace as LegacyWorkspace
        from northstar_api.workspace_invitations import WorkspaceInvitation as LegacyInvitation
        assert Workspace is LegacyWorkspace
        assert WorkspaceInvitation is LegacyInvitation
        assert any(route.path == "/workspace/settings" for route in api_router.routes)
        """,
    ],
)
def test_workspace_model_imports_are_order_independent(imports: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", dedent(imports)],
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
