from itertools import product
from uuid import uuid4

import pytest

from northstar_api.access_policy import (
    ORGANIZATION_GRANTS,
    ORGANIZATION_PERMISSIONS,
    WORKSPACE_GRANTS,
    WORKSPACE_PERMISSIONS,
    effective_permissions,
    permits,
    validate_delegated_permissions,
)
from northstar_api.models import Role, WorkspaceRole
from northstar_api.routers import knowledge
from northstar_api.security import Principal


class ScopeChecked(Exception):
    pass


@pytest.mark.asyncio
@pytest.mark.parametrize("route", [knowledge.list_knowledge, knowledge.create_fact])
async def test_agent_scoped_knowledge_routes_forward_principal_restrictions(
    route, monkeypatch: pytest.MonkeyPatch
) -> None:
    allowed_agent = uuid4()
    principal = Principal(
        user_id=uuid4(), tenant_id=uuid4(), role=Role.MEMBER, token_id=uuid4().hex,
        workspace_id=uuid4(), workspace_role=WorkspaceRole.OPERATOR,
        permissions=frozenset({"knowledge.view", "knowledge.manage"}),
        agent_ids=frozenset({allowed_agent}),
    )

    async def checked(*_args, **kwargs):
        assert kwargs["allowed_agent_ids"] == principal.agent_ids
        raise ScopeChecked

    monkeypatch.setattr(knowledge, "scoped_agent", checked)
    with pytest.raises(ScopeChecked):
        if route is knowledge.list_knowledge:
            await route(allowed_agent, principal, object())
        else:
            await route(allowed_agent, object(), principal, object())

@pytest.mark.parametrize("role", WORKSPACE_GRANTS)
@pytest.mark.parametrize("permission", sorted(ORGANIZATION_PERMISSIONS - {"organization.view"}))
def test_workspace_roles_never_grant_organization_authority(role, permission):
    assert not permits(permission, "member", effective_permissions("member", role), has_workspace=True)

@pytest.mark.parametrize("permission", sorted(WORKSPACE_PERMISSIONS))
def test_org_owner_does_not_override_explicit_viewer_role(permission):
    allowed = permits(permission, "owner", effective_permissions("owner", "viewer"), has_workspace=True)
    assert allowed == (permission in WORKSPACE_GRANTS["viewer"])

@pytest.mark.parametrize("permission", sorted(WORKSPACE_PERMISSIONS))
def test_workspace_grants_require_workspace(permission):
    assert not permits(permission, "owner", effective_permissions("owner", "workspace_admin"), has_workspace=False)

@pytest.mark.parametrize("role,permission", list(product(ORGANIZATION_GRANTS, ORGANIZATION_PERMISSIONS)))
def test_organization_authority_does_not_require_fake_workspace(role, permission):
    assert permits(permission, role, effective_permissions(role, None), has_workspace=False) == (
        permission in ORGANIZATION_GRANTS[role]
    )

def test_unknowns_and_wildcards_deny():
    for permission in ("*", "platform.manage", "billing.typo", "agents.typo"):
        assert not permits(permission, "owner", frozenset({"*", permission}), has_workspace=True)
    assert not permits("billing.manage", "member", frozenset({"*", "billing.manage"}), has_workspace=True)
    assert not (WORKSPACE_PERMISSIONS & ORGANIZATION_PERMISSIONS)
    assert all("*" not in value for value in [*WORKSPACE_GRANTS.values(), *ORGANIZATION_GRANTS.values()])

@pytest.mark.parametrize("permissions", [["*"], ["billing.manage"], ["unknown"], [], ["agents.delete"]])
def test_role_delegation_cannot_escalate(permissions):
    with pytest.raises(ValueError):
        validate_delegated_permissions(permissions, WORKSPACE_GRANTS["viewer"])

def test_valid_delegation():
    assert validate_delegated_permissions(["agents.view"], WORKSPACE_GRANTS["viewer"]) == {"agents.view"}
