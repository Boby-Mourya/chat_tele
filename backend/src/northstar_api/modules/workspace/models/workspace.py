"""Canonical Workspace persistence types; preserve the existing SQLAlchemy mapping.

This module re-exports the legacy mapped class rather than declaring a second
``workspaces`` table or changing its relationships, migrations, or behavior.
"""

from northstar_api.models import Workspace, WorkspaceStatus

__all__ = ["Workspace", "WorkspaceStatus"]
