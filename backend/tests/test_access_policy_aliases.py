from northstar_api.access_policy import (
    PERMISSION_ALIASES,
    WORKSPACE_GRANTS,
    WORKSPACE_PERMISSIONS,
    permits,
    validate_delegated_permissions,
)


def test_public_capability_aliases_are_registered_and_authorized() -> None:
    assert "members.read" in WORKSPACE_PERMISSIONS
    assert "agents.read" in WORKSPACE_PERMISSIONS
    assert PERMISSION_ALIASES["audit.read"] == "audit.view"
    assert permits("members.read", "member", WORKSPACE_GRANTS["workspace_admin"], has_workspace=True)
    assert permits("agents.read", "member", WORKSPACE_GRANTS["viewer"], has_workspace=True)


def test_delegation_accepts_aliases_without_granting_unknown_capabilities() -> None:
    selected = validate_delegated_permissions(["members.read", "workspace.read"], WORKSPACE_GRANTS["workspace_admin"])
    assert selected == frozenset({"members.read", "workspace.read"})
