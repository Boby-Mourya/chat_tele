"""Workspace teams HTTP boundary retaining the existing validated handler.

The original access router remains importable for compatibility; the canonical
Workspace registration uses this feature-specific router.
"""

from fastapi import APIRouter

from northstar_api.modules.workspace.access import update_teams
from northstar_api.modules.workspace.contracts import TeamsSettings

router = APIRouter()
router.patch("/teams", response_model=TeamsSettings)(update_teams)

__all__ = ["router"]
