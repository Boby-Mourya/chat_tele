"""Workspace general-settings HTTP boundary using the existing authorized handler.

The original settings.router stays importable; the aggregate registers this
route only once through this capability-owned module.
"""

from fastapi import APIRouter

from northstar_api.modules.workspace.contracts import GeneralSettings
from northstar_api.modules.workspace.settings import update_general

router = APIRouter()
router.patch("/general", response_model=GeneralSettings)(update_general)

__all__ = ["router"]
