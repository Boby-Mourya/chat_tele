"""Workspace security-settings API boundary; preserve existing authorization."""

from fastapi import APIRouter

from northstar_api.modules.workspace.contracts import SecuritySettings
from northstar_api.modules.workspace.settings import update_security

router = APIRouter()
router.patch("/security", response_model=SecuritySettings)(update_security)

__all__ = ["router"]
