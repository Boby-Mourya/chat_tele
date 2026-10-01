"""Feature-owned Workspace model imports without duplicate ORM mappings.

The existing WorkspaceConversationAssignment export stays eager and unchanged.
Other types resolve lazily so importing authentication or the global model
registry cannot cause a cycle through settings and invitation modules.
"""

from importlib import import_module
from typing import cast

from northstar_api.modules.workspace.conversation_assignment_model import WorkspaceConversationAssignment

_FEATURE_MODELS: dict[str, str] = {
    "Workspace": "workspace",
    "WorkspaceStatus": "workspace",
    "WorkspaceMembership": "workspace_member",
    "WorkspaceMemberAgentAccess": "workspace_member",
    "WorkspaceRole": "workspace_role",
    "CustomRole": "workspace_role",
    "RolesSettings": "workspace_role",
    "WorkspaceTeam": "workspace_team",
    "TeamsSettings": "workspace_team",
    "WorkspaceInvitation": "workspace_invitation",
    "WorkspaceInvitationAgentAccess": "workspace_invitation",
    "WorkspaceInvitationStatus": "workspace_invitation",
}

__all__ = ["WorkspaceConversationAssignment", *_FEATURE_MODELS]


def __getattr__(name: str) -> type[object]:
    """Re-export the original type rather than register a new table/class."""
    module = _FEATURE_MODELS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return cast(type[object], getattr(import_module(f"{__name__}.{module}"), name))
