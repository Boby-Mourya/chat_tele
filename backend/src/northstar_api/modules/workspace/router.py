from fastapi import APIRouter

from .contracts import WorkspaceSettingsBundle
from .settings import get_capabilities, get_settings

from .api import (
    brand_draft_router,
    brand_versions_router,
    conversation_assignments_router,
    dashboard_runtime_router,
    dashboard_settings_router,
    developer_settings_router,
    domains_router,
    email_router,
    general_router,
    general_settings_router,
    members_router,
    notifications_settings_router,
    roles_router,
    security_settings_router,
    teams_router,
)

router = APIRouter(prefix="/workspace/settings", tags=["workspace-settings"])
# The original combined settings_router remains importable for compatibility;
# only its canonical read/write capability routers are registered here.
router.get("", response_model=WorkspaceSettingsBundle)(get_settings)
router.get("/capabilities")(get_capabilities)
router.include_router(general_settings_router)
router.include_router(security_settings_router)
router.include_router(notifications_settings_router)
router.include_router(developer_settings_router)
router.include_router(general_router)
router.include_router(members_router)
# Register each existing access capability once through its canonical boundary.
# The combined access_router remains exported for legacy callers.
router.include_router(roles_router)
router.include_router(teams_router)
router.include_router(dashboard_settings_router)
router.include_router(conversation_assignments_router)
router.include_router(dashboard_runtime_router)
# Draft and published branding have separate canonical boundaries; retain the
# original combined branding_router for import compatibility, not registration.
router.include_router(brand_draft_router)
router.include_router(brand_versions_router)
router.include_router(domains_router)
router.include_router(email_router)
