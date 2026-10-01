from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select

from northstar_api.access_policy import ORGANIZATION_PERMISSIONS, WORKSPACE_PERMISSIONS
from northstar_api.dependencies import CurrentPrincipal, DBSession
from northstar_api.models import Tenant, Workspace
from northstar_api.onboarding_contract import BrandingChoiceSave, ProfileSave, granted_starter_content
from northstar_api.services.entitlements import entitlement_context
from northstar_api.services.onboarding import load_setup, save_branding_choice, save_profile, setup_response
from northstar_api.workspace_contract import WhiteLabelSettings, safe_legacy_read

router = APIRouter(tags=["organization-onboarding"])


@router.get("/bootstrap")
async def bootstrap(principal: CurrentPrincipal, session: DBSession, response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "private, no-store"
    if principal.token_id.startswith("api_key:"):
        raise HTTPException(status_code=403, detail="An interactive session is required")
    tenant = await session.scalar(select(Tenant).where(Tenant.id == principal.tenant_id))
    if tenant is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    setup = await load_setup(session, principal)
    context = await entitlement_context(session, tenant_id=principal.tenant_id)
    workspace = await session.scalar(select(Workspace).where(
        Workspace.tenant_id == principal.tenant_id, Workspace.id == principal.workspace_id,
    )) if principal.workspace_id else None
    onboarding = setup_response(setup)
    if not principal.can("organization.profile.update"):
        onboarding.pop("profile", None)
        onboarding.pop("draft", None)
    policy = context.policy
    brand_warnings: list[str] = []
    brand = safe_legacy_read(WhiteLabelSettings, dict(workspace.branding_json or {}) if workspace else {}, brand_warnings)
    return {
        "organization": {"id": str(tenant.id), "name": tenant.name, "role": principal.role.value},
        "workspaceId": str(workspace.id) if workspace else None,
        "capabilities": {
            "organization": sorted(principal.permissions & ORGANIZATION_PERMISSIONS),
            "workspace": sorted(principal.permissions & WORKSPACE_PERMISSIONS),
        },
        "onboarding": onboarding,
        "starterContent": granted_starter_content(list(setup.catalog_grants)) if principal.can("starter_content.read") else [],
        "plan": {
            "name": context.subscription.plan, "status": context.subscription.status.value,
            "workspaceLimit": policy.workspace_limit, "agentLimit": policy.agent_limit,
            "memberLimit": policy.member_limit, "monthlyConversationLimit": policy.conversation_limit_monthly,
            "monthlyTokenLimit": policy.token_limit_monthly, "storageLimitBytes": policy.storage_limit_bytes,
            "dashboardCustomize": policy.white_label_enabled,
            "customDomain": policy.custom_domain_enabled, "brandedEmail": policy.branded_email_enabled,
            "removePlatformMark": policy.remove_platform_mark_enabled,
        },
        "usage": {
            "workspaces": context.usage.workspaces, "agents": context.usage.agents,
            "members": context.usage.members, "pendingSeats": context.usage.pending_member_seats,
            "conversationsMonthly": context.usage.conversations_monthly,
            "tokensMonthly": context.usage.tokens_monthly, "storageBytes": context.usage.storage_bytes,
        } if principal.can("usage.view") else None,
        "brand": brand.model_dump(by_alias=True, mode="json"),
        "brandingWarnings": brand_warnings,
    }


@router.get("/organization/profile")
@router.get("/onboarding")
async def get_onboarding(principal: CurrentPrincipal, session: DBSession, response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "private, no-store"
    if not principal.can("organization.profile.update") or principal.token_id.startswith("api_key:"):
        raise HTTPException(status_code=403, detail="Organization profile permission required")
    return setup_response(await load_setup(session, principal))


@router.patch("/organization/profile")
async def patch_profile(payload: ProfileSave, principal: CurrentPrincipal, session: DBSession) -> dict[str, Any]:
    return await save_profile(session, principal, payload)


@router.patch("/onboarding")
async def patch_onboarding(payload: BrandingChoiceSave, principal: CurrentPrincipal, session: DBSession) -> dict[str, Any]:
    return await save_branding_choice(session, principal, payload)


@router.get("/starter-content")
async def starter_content(principal: CurrentPrincipal, session: DBSession) -> list[dict[str, str | int | bool]]:
    if not principal.can("starter_content.read"):
        raise HTTPException(status_code=403, detail="Starter content permission required")
    setup = await load_setup(session, principal)
    return granted_starter_content(list(setup.catalog_grants))
