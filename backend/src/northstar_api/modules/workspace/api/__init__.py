"""Canonical HTTP boundary for workspace administration.

The concrete routers still live in compatibility modules during the staged
migration. New production imports should use this package so those modules can
be moved one capability at a time without changing application registration.
"""

from northstar_api.modules.branding.api import (
    brand_draft_router,
    brand_versions_router,
    branding_router,
    domains_router,
    email_router,
)
from northstar_api.modules.workspace.access import router as access_router
from northstar_api.modules.workspace.conversation_assignments import router as conversation_assignments_router
from northstar_api.modules.workspace.dashboard_runtime import router as dashboard_runtime_router
from northstar_api.modules.workspace.general import router as general_router

from .workspace_dashboard import router as dashboard_settings_router
from .workspace_developer import router as developer_settings_router
from .workspace_general_settings import router as general_settings_router
from .workspace_members import router as members_router
from .workspace_notifications import router as notifications_settings_router
from .workspace_roles import router as roles_router
from .workspace_security import router as security_settings_router
from .workspace_settings import router as settings_router
from .workspace_settings_core import router as settings_core_router
from .workspace_teams import router as teams_router

__all__ = [
    "access_router",  # Retain the original combined router for legacy imports.
    "brand_draft_router",
    "brand_versions_router",
    "branding_router",  # Retain combined branding router for legacy imports.
    "conversation_assignments_router",
    "dashboard_runtime_router",
    "dashboard_settings_router",
    "developer_settings_router",
    "domains_router",
    "email_router",
    "general_router",
    "general_settings_router",
    "members_router",
    "notifications_settings_router",
    "roles_router",
    "security_settings_router",
    "settings_core_router",
    "settings_router",  # Original all-in-one settings router remains available.
    "teams_router",
]
