"""Canonical Workspace brand publication/version HTTP boundary.

Keep the original publication and rollback handlers and their transactional
persistence, entitlement checks, audit and cache invalidation unchanged.
"""

from fastapi import APIRouter

from northstar_api.modules.workspace.branding import publish_branding, rollback_branding
from northstar_api.modules.workspace.contracts import BrandVersion

router = APIRouter()
router.post("/branding/publish", response_model=BrandVersion)(publish_branding)
router.post("/branding/rollback", response_model=BrandVersion)(rollback_branding)

__all__ = ["router"]
