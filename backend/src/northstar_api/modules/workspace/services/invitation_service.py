"""Canonical Workspace invitation service import path.

Invitation issuance, acceptance, delivery and revocation are already implemented
by ``northstar_api.services.workspace_invitations`` and its existing routers.
Re-export the *same function and contract objects* here instead of duplicating
state transitions, token handling, persistence, email delivery or transactions.
The teammate-owned implementation and registration remain unchanged.
"""

from northstar_api.services.workspace_invitations import (
    AcceptedWorkspaceInvitation,
    IssuedWorkspaceInvitation,
    WorkspaceInvitationDetails,
    WorkspaceInvitationError,
    accept_workspace_invitation,
    decline_workspace_invitation,
    issue_workspace_invitation,
    list_invitation_agent_ids,
    list_workspace_invitations,
    mark_workspace_invitation_delivery,
    normalize_invitation_email,
    preview_workspace_invitation,
    resend_workspace_invitation,
    revoke_workspace_invitation,
    send_workspace_invitation_email,
    signup_with_workspace_invitation,
    workspace_invitation_token_hash,
    workspace_invitation_url,
)

__all__ = [
    "AcceptedWorkspaceInvitation",
    "IssuedWorkspaceInvitation",
    "WorkspaceInvitationDetails",
    "WorkspaceInvitationError",
    "accept_workspace_invitation",
    "decline_workspace_invitation",
    "issue_workspace_invitation",
    "list_invitation_agent_ids",
    "list_workspace_invitations",
    "mark_workspace_invitation_delivery",
    "normalize_invitation_email",
    "preview_workspace_invitation",
    "resend_workspace_invitation",
    "revoke_workspace_invitation",
    "send_workspace_invitation_email",
    "signup_with_workspace_invitation",
    "workspace_invitation_token_hash",
    "workspace_invitation_url",
]
