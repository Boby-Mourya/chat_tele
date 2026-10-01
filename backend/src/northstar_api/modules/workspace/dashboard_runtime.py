from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from northstar_api.dependencies import DBSession, require_permissions
from northstar_api.entitlements import entitlement_for_plan
from northstar_api.modules.branding.services import resolve_published_workspace_brand
from northstar_api.onboarding_contract import SetupContract
from northstar_api.security import Principal

from .contracts import DashboardAppearance, DashboardSettings
from .store import load_workspace, settings_document

router = APIRouter()
WorkspaceViewPrincipal = Annotated[Principal, Depends(require_permissions("workspace.view"))]


class WorkspaceDashboardRuntime(SetupContract):
    dashboard: DashboardSettings
    appearance: DashboardAppearance
    industry: str = ""
    country: str = ""
    enabled_features: list[str]


@router.get("/runtime-dashboard", response_model=WorkspaceDashboardRuntime)
async def get_runtime_dashboard(
    principal: WorkspaceViewPrincipal,
    session: DBSession,
) -> WorkspaceDashboardRuntime:
    tenant, workspace = await load_workspace(principal, session)
    document = settings_document(workspace)
    published, _ = await resolve_published_workspace_brand(session, workspace)
    dashboard = published.dashboard if published is not None else document.dashboard
    # A draft is a private editing surface, not the live workspace appearance.
    # Preserve the existing live dashboard settings until a brand is published,
    # but never expose unpublished appearance settings to regular viewers.
    appearance = published.appearance if published is not None else DashboardAppearance()
    entitlement = entitlement_for_plan(tenant.plan)
    features = {f"channel:{name}" for name in entitlement.allowed_channels}
    if entitlement.crm_enabled:
        features.add("crm")
    if entitlement.api_enabled:
        features.add("api")
    if entitlement.white_label_enabled:
        features.add("white-label")
    if entitlement.custom_domain_enabled:
        features.add("custom-domain")
    if entitlement.branded_email_enabled:
        features.add("branded-email")
    return WorkspaceDashboardRuntime(
        dashboard=dashboard,
        appearance=appearance,
        industry=document.general.industry,
        country=document.general.country,
        enabled_features=sorted(features),
    )
