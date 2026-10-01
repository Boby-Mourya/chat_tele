"""Workspace roles HTTP boundary, preserving the existing handler and route contract.

The legacy access router continues to expose the same endpoint for existing
imports. The canonical Workspace router registers this capability only once.
"""

from fastapi import APIRouter

from northstar_api.modules.workspace.access import update_roles
from northstar_api.modules.workspace.contracts import RolesSettings

router = APIRouter()
router.patch("/roles", response_model=RolesSettings)(update_roles)

__all__ = ["router"]
