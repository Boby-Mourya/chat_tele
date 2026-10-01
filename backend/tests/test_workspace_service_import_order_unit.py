"""Section 23: service boundaries must initialize in either import order."""

from __future__ import annotations

import subprocess
import sys
from textwrap import dedent

import pytest


@pytest.mark.parametrize(
    "imports",
    [
        """
        from northstar_api.modules.workspace.services.member_service import ensure_ownership_transfer_allowed
        from northstar_api.modules.workspace.members import transfer_ownership
        from northstar_api.modules.workspace.services.settings_service import update_general_settings
        from northstar_api.modules.workspace.settings import update_general
        from northstar_api.modules.workspace.services.role_service import update_workspace_roles
        from northstar_api.modules.workspace.services.team_service import update_workspace_teams
        from northstar_api.modules.workspace.services.dashboard_service import update_workspace_dashboard
        from northstar_api.modules.workspace.access import update_roles, update_teams, update_dashboard
        assert callable(ensure_ownership_transfer_allowed)
        assert callable(transfer_ownership)
        assert callable(update_general_settings)
        assert callable(update_general)
        assert callable(update_workspace_roles)
        assert callable(update_workspace_teams)
        assert callable(update_workspace_dashboard)
        assert callable(update_roles)
        assert callable(update_teams)
        assert callable(update_dashboard)
        """,
        """
        from northstar_api.modules.workspace.access import update_roles, update_teams, update_dashboard
        from northstar_api.modules.workspace.settings import update_general
        from northstar_api.modules.workspace.members import transfer_ownership
        from northstar_api.modules.workspace.services.settings_service import update_general_settings
        from northstar_api.modules.workspace.services.member_service import ensure_ownership_transfer_allowed
        from northstar_api.modules.workspace.services.role_service import update_workspace_roles
        from northstar_api.modules.workspace.services.team_service import update_workspace_teams
        from northstar_api.modules.workspace.services.dashboard_service import update_workspace_dashboard
        assert callable(ensure_ownership_transfer_allowed)
        assert callable(transfer_ownership)
        assert callable(update_general_settings)
        assert callable(update_general)
        assert callable(update_workspace_roles)
        assert callable(update_workspace_teams)
        assert callable(update_workspace_dashboard)
        assert callable(update_roles)
        assert callable(update_teams)
        assert callable(update_dashboard)
        """,
        """
        from northstar_api.routers import api_router
        from northstar_api.modules.workspace.services.member_service import ensure_ownership_transfer_allowed
        from northstar_api.modules.workspace.services.settings_service import update_general_settings
        from northstar_api.modules.workspace.services.role_service import update_workspace_roles
        from northstar_api.modules.workspace.services.team_service import update_workspace_teams
        from northstar_api.modules.workspace.services.dashboard_service import update_workspace_dashboard
        assert callable(ensure_ownership_transfer_allowed)
        assert callable(update_general_settings)
        assert callable(update_workspace_roles)
        assert callable(update_workspace_teams)
        assert callable(update_workspace_dashboard)
        assert any(route.path == "/workspace/settings" for route in api_router.routes)
        """,
    ],
)
def test_workspace_services_and_legacy_handlers_import_in_either_order(imports: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", dedent(imports)],
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
