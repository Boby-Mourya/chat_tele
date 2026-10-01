"""Versioned access contracts shared by the API and its generated role editor."""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from northstar_api.access_policy import WORKSPACE_PERMISSIONS
from northstar_api.onboarding_contract import SetupContract

ResourceKind = Literal['agents', 'knowledge', 'conversations', 'courses', 'batches', 'students', 'leads', 'channels', 'crm']


class ResourcePolicy(SetupContract):
    # An omitted kind is unrestricted within the workspace; [] explicitly denies it.
    selected: dict[ResourceKind, list[UUID]] = Field(default_factory=dict, max_length=9)
    conversation_scope: Literal['all', 'assigned', 'team'] = 'all'

    @field_validator('selected')
    @classmethod
    def bounded(cls, value: dict[ResourceKind, list[UUID]]) -> dict[ResourceKind, list[UUID]]:
        if any(len(ids) > 500 for ids in value.values()):
            raise ValueError('Use a team or collection instead of more than 500 individual grants')
        return {kind: list(dict.fromkeys(ids)) for kind, ids in value.items()}


def validate_policy_delegation(requested: ResourcePolicy, ceiling: ResourcePolicy) -> None:
    for kind, allowed in ceiling.selected.items():
        wanted = requested.selected.get(kind)
        if wanted is None or not set(wanted) <= set(allowed):
            raise ValueError(f'Cannot broaden {kind} resource access')
    scope_rank = {'assigned': 0, 'team': 1, 'all': 2}
    if scope_rank[requested.conversation_scope] > scope_rank[ceiling.conversation_scope]:
        raise ValueError('Cannot broaden conversation visibility')


class RoleSave(SetupContract):
    expected_version: int = Field(default=0, ge=0)
    name: str = Field(min_length=2, max_length=80)
    description: str = Field(default='', max_length=500)
    permissions: list[str] = Field(min_length=1, max_length=150)
    resources: ResourcePolicy = Field(default_factory=ResourcePolicy)

    @field_validator('name')
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        result = ' '.join(value.split())
        if len(result) < 2:
            raise ValueError('Provide a visible role name')
        return result

    @field_validator('permissions')
    @classmethod
    def known_permissions(cls, values: list[str]) -> list[str]:
        selected = set(values)
        if not selected <= WORKSPACE_PERMISSIONS:
            raise ValueError('Only registered workspace permissions can be assigned')
        return sorted(selected)


class VersionRequest(SetupContract):
    expected_version: int = Field(ge=0)


class MemberPolicySave(VersionRequest):
    custom_role_id: UUID | None = None
    builtin_role: Literal['workspace_admin', 'manager', 'operator', 'analyst', 'viewer'] | None = None
    status: Literal['active', 'suspended'] = 'active'
    team_only: bool = False
    all_agents_access: bool = False
    agent_ids: list[UUID] = Field(default_factory=list, max_length=500)

    @model_validator(mode='after')
    def one_role(self) -> MemberPolicySave:
        if sum([self.custom_role_id is not None, self.builtin_role is not None, self.team_only]) != 1:
            raise ValueError('Choose exactly one built-in role, custom role or team-only access')
        if self.all_agents_access and self.agent_ids:
            raise ValueError('Choose all agents or an explicit selection, not both')
        return self


class TeamSave(VersionRequest):
    name: str = Field(min_length=2, max_length=80)
    description: str = Field(default='', max_length=500)
    member_ids: list[UUID] = Field(default_factory=list, max_length=500)
    role_ids: list[UUID] = Field(default_factory=list, max_length=50)

    @field_validator('name')
    @classmethod
    def visible_name(cls, value: str) -> str:
        return RoleSave.name_not_blank(value)


class ConversationAssignmentSave(VersionRequest):
    user_id: UUID | None = None
    team_id: UUID | None = None

    @model_validator(mode='after')
    def one_recipient(self) -> ConversationAssignmentSave:
        if self.user_id is not None and self.team_id is not None:
            raise ValueError('Assign a conversation to a user or a team, not both')
        return self
