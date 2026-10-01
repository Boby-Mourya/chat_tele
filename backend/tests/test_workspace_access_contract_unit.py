from uuid import uuid4

import pytest
from pydantic import ValidationError

from northstar_api.resource_policy import ResourceGrant, grant_covers
from northstar_api.workspace_access_contract import MemberPolicySave, ResourcePolicy, RoleSave, TeamSave, validate_policy_delegation


def test_team_only_membership_does_not_require_a_viewer_grant():
    value = MemberPolicySave(expectedVersion=0, teamOnly=True)
    assert value.custom_role_id is None and value.builtin_role is None


@pytest.mark.parametrize('values', [
    {}, {'builtinRole': 'viewer', 'teamOnly': True},
    {'builtinRole': 'viewer', 'customRoleId': str(uuid4())},
    {'customRoleId': str(uuid4()), 'teamOnly': True},
])
def test_exactly_one_membership_role_source(values):
    with pytest.raises(ValidationError):
        MemberPolicySave(expectedVersion=0, **values)


@pytest.mark.parametrize('permission', ['*', 'billing.manage', 'organization.ownership.transfer', 'unknown'])
def test_custom_roles_never_contain_organization_or_unknown_authority(permission):
    with pytest.raises(ValidationError):
        RoleSave(name='Scoped role', permissions=[permission])


def test_selected_empty_means_deny_not_unrestricted():
    value = ResourceGrant.from_json(['agents.view'], {'selected': {'agents': []}})
    assert value.ids_for('agents') == frozenset()
    assert not value.permits('agents.view', 'agents', uuid4())
    assert value.ids_for('courses') is None


def test_union_does_not_change_permission_specific_grants():
    allowed, foreign = uuid4(), uuid4()
    viewer = ResourceGrant.from_json(['agents.view'], {'selected': {'agents': [str(allowed)]}})
    editor = ResourceGrant.from_json(['agents.update'], {'selected': {'agents': [str(foreign)]}})
    assert viewer.permits('agents.view', 'agents', allowed)
    assert not viewer.permits('agents.view', 'agents', foreign)
    assert not editor.permits('agents.view', 'agents', foreign)


@pytest.mark.parametrize('scope,assigned,team,expected', [
    ('all', False, False, True), ('assigned', False, True, False),
    ('assigned', True, False, True), ('team', False, True, True),
    ('team', True, False, True), ('team', False, False, False),
])
def test_conversation_scope(scope, assigned, team, expected):
    grant = ResourceGrant(frozenset({'conversations.view'}), conversation_scope=scope)
    assert grant.permits('conversations.view', 'conversations', uuid4(), assigned=assigned, in_team=team) is expected


def test_delegation_cannot_drop_parent_restrictions():
    allowed, foreign = uuid4(), uuid4()
    ceiling = ResourcePolicy(selected={'agents': [allowed]}, conversationScope='team')
    for requested in [ResourcePolicy(), ResourcePolicy(selected={'agents': [foreign]}, conversationScope='team'),
                      ResourcePolicy(selected={'agents': [allowed]}, conversationScope='all')]:
        with pytest.raises(ValueError):
            validate_policy_delegation(requested, ceiling)
    validate_policy_delegation(ResourcePolicy(selected={'agents': []}, conversationScope='assigned'), ceiling)


def test_grant_ceiling_checks_action_and_selected_ids():
    agent = uuid4()
    ceiling = ResourceGrant.from_json(['agents.view'], {'selected': {'agents': [str(agent)]}})
    assert grant_covers(ceiling, ceiling)
    assert not grant_covers(ceiling, ResourceGrant(frozenset({'agents.view'})))
    assert not grant_covers(ceiling, ResourceGrant(frozenset({'agents.delete'})))


def test_names_and_selectors_are_bounded():
    assert TeamSave(expectedVersion=0, name=' A  team ').name == 'A team'
    with pytest.raises(ValidationError):
        RoleSave(name='  ', permissions=['workspace.view'])
    with pytest.raises(ValidationError):
        ResourcePolicy(selected={'agents': [uuid4() for _ in range(501)]})
    with pytest.raises(ValidationError):
        MemberPolicySave(expectedVersion=0, builtinRole='viewer', allAgentsAccess=True, agentIds=[uuid4()])
