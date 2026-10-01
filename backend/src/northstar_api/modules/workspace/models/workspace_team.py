"""Workspace team types backed by the existing validated settings document.

Teams are not a standalone ORM table in this compatibility stage. Exposing the
same contract avoids inventing parallel persistence before a tested migration.
"""

from northstar_api.modules.workspace.contracts import TeamsSettings, WorkspaceTeam

__all__ = ["TeamsSettings", "WorkspaceTeam"]
