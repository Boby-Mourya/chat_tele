"""Canonical Workspace brand reading and draft-editing API.

The existing Workspace branding handler functions remain the implementation
and the combined legacy router remains importable during staged migration.
Only this capability router is registered in the production Workspace router.
"""

from fastapi import APIRouter

from northstar_api.modules.workspace.branding import (
    get_branding,
    get_runtime_branding,
    save_branding_draft,
)
from northstar_api.modules.workspace.contracts import BrandingSettingsView, ExtendedBranding

router = APIRouter()
router.get("/branding", response_model=BrandingSettingsView)(get_branding)
router.get("/runtime-branding", response_model=ExtendedBranding | None)(get_runtime_branding)
router.patch("/branding/draft", response_model=ExtendedBranding)(save_branding_draft)

__all__ = ["router"]
