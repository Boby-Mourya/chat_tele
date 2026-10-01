"""Immutable resource grants; membership restrictions intersect role/team grants."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ResourceGrant:
    permissions: frozenset[str]
    selected: tuple[tuple[str, frozenset[UUID]], ...] = ()
    conversation_scope: str = 'all'

    @classmethod
    def from_json(cls, permissions: list[str] | frozenset[str], value: dict[str, Any]) -> ResourceGrant:
        from northstar_api.access_policy import WORKSPACE_PERMISSIONS
        from northstar_api.workspace_access_contract import ResourcePolicy
        policy = ResourcePolicy.model_validate(value)
        chosen = frozenset(permissions)
        if not chosen <= WORKSPACE_PERMISSIONS:
            raise ValueError('Stored workspace grant contains an invalid permission')
        return cls(chosen, tuple((key, frozenset(ids)) for key, ids in policy.selected.items()), policy.conversation_scope)

    def ids_for(self, kind: str) -> frozenset[UUID] | None:
        return dict(self.selected).get(kind)

    def permits(self, permission: str, kind: str, resource_id: UUID, *, assigned: bool = False, in_team: bool = False) -> bool:
        if permission not in self.permissions:
            return False
        ids = self.ids_for(kind)
        if ids is not None and resource_id not in ids:
            return False
        if kind == 'conversations':
            if self.conversation_scope == 'assigned' and not assigned:
                return False
            if self.conversation_scope == 'team' and not (assigned or in_team):
                return False
        return True


def grant_covers(actor: ResourceGrant, requested: ResourceGrant) -> bool:
    if not requested.permissions <= actor.permissions:
        return False
    for kind, allowed in actor.selected:
        wanted = requested.ids_for(kind)
        if wanted is None or not wanted <= allowed:
            return False
    ranks = {'assigned': 0, 'team': 1, 'all': 2}
    return ranks.get(requested.conversation_scope, 99) <= ranks.get(actor.conversation_scope, -1)
