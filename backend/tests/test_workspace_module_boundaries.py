from fastapi import APIRouter

from northstar_api.modules.branding import branding_router, domains_router, email_router
from northstar_api.modules.branding.api.domain_routes import router as canonical_domains_router
from northstar_api.modules.workspace.api import (
    access_router,
    conversation_assignments_router,
    dashboard_settings_router,
    general_router,
    members_router,
    roles_router,
    settings_router,
    teams_router,
)
from northstar_api.modules.workspace.models import WorkspaceConversationAssignment
from northstar_api.modules.workspace.permissions import WORKSPACE_PERMISSIONS
from northstar_api.modules.workspace.repositories import settings_document
from northstar_api.modules.workspace.router import router as workspace_settings_router
from northstar_api.modules.workspace.schemas import WorkspaceSettingsBundle


def test_workspace_feature_boundaries_are_importable() -> None:
    routers = [
        workspace_settings_router,
        settings_router,
        general_router,
        members_router,
        access_router,
        roles_router,
        teams_router,
        dashboard_settings_router,
        conversation_assignments_router,
        branding_router,
        domains_router,
        email_router,
    ]
    assert all(isinstance(value, APIRouter) for value in routers)
    assert canonical_domains_router is domains_router
    assert WorkspaceConversationAssignment.__tablename__ == "workspace_conversation_assignments"
    assert "workspace.view" in WORKSPACE_PERMISSIONS
    assert callable(settings_document)
    assert WorkspaceSettingsBundle().general.currency == "INR"
