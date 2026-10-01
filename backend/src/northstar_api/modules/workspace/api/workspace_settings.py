"""Canonical settings HTTP boundary for staged Workspace module migration.

Keep the original permission checks, persistence and route definitions owned by
``modules.workspace.settings`` until that capability is migrated and tested.
"""

from northstar_api.modules.workspace.settings import router

__all__ = ["router"]
