"""Workspace authorization helpers and capability mapping."""

from northstar_api.access_policy import WORKSPACE_GRANTS, WORKSPACE_PERMISSIONS, validate_delegated_permissions
from northstar_api.modules.workspace.api_key_scopes import permissions_for_api_key_scopes
from northstar_api.modules.workspace.conversation_scope import set_conversation_assignment_scope

__all__ = [
    "WORKSPACE_GRANTS",
    "WORKSPACE_PERMISSIONS",
    "permissions_for_api_key_scopes",
    "set_conversation_assignment_scope",
    "validate_delegated_permissions",
]
