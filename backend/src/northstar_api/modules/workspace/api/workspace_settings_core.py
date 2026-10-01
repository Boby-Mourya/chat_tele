"""Workspace settings read-only HTTP routes for staged capability registration.

Keep the original settings.router and existing handlers available for all
compatibility imports. Only this read-only router is registered alongside the
capability-owned PATCH routers in the production Workspace aggregate.
"""

from fastapi import APIRouter

from northstar_api.modules.workspace.contracts import WorkspaceSettingsBundle
from northstar_api.modules.workspace.settings import get_capabilities, get_settings

router = APIRouter()
router.get("", response_model=WorkspaceSettingsBundle)(get_settings)
router.get("/capabilities")(get_capabilities)

__all__ = ["router"]
