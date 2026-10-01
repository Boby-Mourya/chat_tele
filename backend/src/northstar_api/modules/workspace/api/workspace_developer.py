"""Workspace developer-settings API boundary using the existing handler."""

from fastapi import APIRouter

from northstar_api.modules.workspace.contracts import DeveloperSettings
from northstar_api.modules.workspace.settings import update_developer

router = APIRouter()
router.patch("/developer", response_model=DeveloperSettings)(update_developer)

__all__ = ["router"]
