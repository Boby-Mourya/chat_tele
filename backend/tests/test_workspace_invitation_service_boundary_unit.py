"""Section 23: canonical invitation imports preserve the teammate-owned lifecycle."""

from __future__ import annotations

import subprocess
import sys
from textwrap import dedent

import pytest

from northstar_api.modules.workspace.services import invitation_service as canonical
from northstar_api.services import workspace_invitations as legacy


@pytest.mark.parametrize("name", canonical.__all__)
def test_canonical_invitation_service_uses_original_implementation(name: str) -> None:
    """Do not fork token, validation, acceptance, delivery or transaction logic."""
    assert getattr(canonical, name) is getattr(legacy, name)


def test_canonical_invitation_service_exports_the_entire_contract() -> None:
    expected = {
        "WorkspaceInvitationError",
        "IssuedWorkspaceInvitation",
        "WorkspaceInvitationDetails",
        "AcceptedWorkspaceInvitation",
        "normalize_invitation_email",
        "workspace_invitation_token_hash",
        "issue_workspace_invitation",
        "resend_workspace_invitation",
        "mark_workspace_invitation_delivery",
        "list_workspace_invitations",
        "list_invitation_agent_ids",
        "revoke_workspace_invitation",
        "preview_workspace_invitation",
        "accept_workspace_invitation",
        "signup_with_workspace_invitation",
        "decline_workspace_invitation",
        "workspace_invitation_url",
        "send_workspace_invitation_email",
    }
    assert set(canonical.__all__) == expected


@pytest.mark.parametrize(
    "imports",
    [
        """
        from northstar_api.modules.workspace.services.invitation_service import issue_workspace_invitation
        from northstar_api.services.workspace_invitations import issue_workspace_invitation as original
        from northstar_api.modules.workspace.api.workspace_invitations import router, public_router
        from northstar_api.routers.workspace_invitations import router as legacy_router
        from northstar_api.routers.workspace_invitations import public_router as legacy_public_router
        assert issue_workspace_invitation is original
        assert router is legacy_router
        assert public_router is legacy_public_router
        """,
        """
        from northstar_api.routers.workspace_invitations import router as legacy_router
        from northstar_api.routers.workspace_invitations import public_router as legacy_public_router
        from northstar_api.services.workspace_invitations import accept_workspace_invitation as original
        from northstar_api.modules.workspace.api.workspace_invitations import router, public_router
        from northstar_api.modules.workspace.services.invitation_service import accept_workspace_invitation
        assert accept_workspace_invitation is original
        assert router is legacy_router
        assert public_router is legacy_public_router
        """,
    ],
)
def test_invitation_service_and_api_import_in_either_order(imports: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", dedent(imports)],
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
