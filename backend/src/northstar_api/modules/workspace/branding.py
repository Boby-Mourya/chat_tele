from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from northstar_api.dependencies import DBSession, require_permissions
from northstar_api.entitlements import entitlement_for_plan
from northstar_api.models import Workspace
from northstar_api.modules.branding.repositories import persist_branding_document
from northstar_api.modules.branding.services import resolve_published_workspace_brand
from northstar_api.security import Principal

from .brand_cache import cache_version_brand, invalidate_brand_cache
from .contracts import (
    BrandingSettingsView,
    BrandVersion,
    ExtendedBranding,
    PublishRequest,
    RollbackRequest,
    WorkspaceSettingsBundle,
)
from .repositories.workspace_write_lock import lock_workspace_settings
from .store import load_workspace, record_workspace_change, save_document, settings_document

router = APIRouter()
BrandViewPrincipal = Annotated[Principal, Depends(require_permissions("branding.view"))]
BrandEditPrincipal = Annotated[Principal, Depends(require_permissions("branding.edit"))]
BrandPublishPrincipal = Annotated[Principal, Depends(require_permissions("branding.publish"))]
RuntimeBrandPrincipal = Annotated[Principal, Depends(require_permissions("workspace.view"))]


def _interactive_only(principal: Principal, operation: str) -> None:
    if principal.token_id.startswith("api_key:"):
        raise HTTPException(status_code=403, detail=f"Interactive branding {operation} required")


def _check_brand_entitlements(plan: str, branding: ExtendedBranding) -> None:
    entitlement = entitlement_for_plan(plan)
    if not entitlement.white_label_enabled:
        raise HTTPException(status_code=403, detail="Your plan does not include white label")
    if branding.identity.branded_emails and not entitlement.branded_email_enabled:
        raise HTTPException(status_code=403, detail="Your plan does not include branded email")
    if branding.identity.remove_platform_branding and not entitlement.remove_platform_mark_enabled:
        raise HTTPException(status_code=403, detail="Your plan does not include platform-brand removal")


async def _publish(
    document: WorkspaceSettingsBundle,
    principal: Principal,
    session: DBSession,
    workspace: Workspace,
    plan: str,
    change_note: str,
    *,
    request: Request,
    action: str = "workspace.brand.published",
) -> BrandVersion:
    _check_brand_entitlements(plan, document.branding_draft)
    before = (
        document.branding_published.model_dump(by_alias=True, mode="json")
        if document.branding_published is not None
        else {}
    )
    version_number = max((item.version for item in document.branding_versions), default=0) + 1
    version = BrandVersion(
        version=version_number,
        created_by=str(principal.user_id),
        published_at=datetime.now(UTC),
        change_note=change_note,
        branding=document.branding_draft.model_copy(deep=True),
    )
    document.branding_published = version.branding.model_copy(deep=True)
    document.branding_versions = (document.branding_versions + [version])[-50:]
    active_domain = next(
        (item.hostname for item in document.domains.domains if item.status == "active"),
        "",
    )
    workspace.branding_json = {
        **version.branding.identity.model_dump(by_alias=True, mode="json"),
        "customDomain": active_domain,
        "dnsStatus": "verified" if active_domain else "not-configured",
    }
    save_document(workspace, document)
    await persist_branding_document(session, workspace, document, published_version=version)
    record_workspace_change(
        session,
        principal,
        workspace,
        action,
        [f"version:{version_number}"],
        resource_type="workspace_brand_version",
        resource_id=f"{workspace.id}:{version_number}",
        before=before,
        after=version.branding.model_dump(by_alias=True, mode="json"),
        reason=change_note or None,
        request=request,
    )
    await session.commit()
    payload = version.branding.model_dump(by_alias=True, mode="json")
    await cache_version_brand(workspace.id, version_number, payload)
    await invalidate_brand_cache(
        workspace.id,
        hostnames=[item.hostname for item in document.domains.domains],
        version=version_number,
    )
    return version


@router.get("/branding", response_model=BrandingSettingsView)
async def get_branding(
    principal: BrandViewPrincipal,
    session: DBSession,
) -> BrandingSettingsView:
    _, workspace = await load_workspace(principal, session)
    document = settings_document(workspace)
    return BrandingSettingsView(
        branding_draft=document.branding_draft,
        branding_published=document.branding_published,
        branding_versions=document.branding_versions,
        domains=document.domains,
    )


@router.get("/runtime-branding", response_model=ExtendedBranding | None)
async def get_runtime_branding(
    principal: RuntimeBrandPrincipal,
    session: DBSession,
) -> ExtendedBranding | None:
    _, workspace = await load_workspace(principal, session)
    published, _ = await resolve_published_workspace_brand(session, workspace)
    return published


@router.patch("/branding/draft", response_model=ExtendedBranding)
async def save_branding_draft(
    payload: ExtendedBranding,
    request: Request,
    principal: BrandEditPrincipal,
    session: DBSession,
) -> ExtendedBranding:
    _interactive_only(principal, "editing")
    _, workspace = await load_workspace(principal, session)
    await lock_workspace_settings(session, workspace)
    document = settings_document(workspace)
    before = document.branding_draft.model_dump(by_alias=True, mode="json")
    document.branding_draft = payload
    save_document(workspace, document)
    await persist_branding_document(session, workspace, document)
    record_workspace_change(
        session,
        principal,
        workspace,
        "workspace.brand.draft.updated",
        ["brandingDraft"],
        resource_type="workspace_brand",
        resource_id=str(workspace.id),
        before=before,
        after=payload.model_dump(by_alias=True, mode="json"),
        request=request,
    )
    await session.commit()
    return payload


@router.post("/branding/publish", response_model=BrandVersion)
async def publish_branding(
    payload: PublishRequest,
    request: Request,
    principal: BrandPublishPrincipal,
    session: DBSession,
) -> BrandVersion:
    _interactive_only(principal, "publication")
    tenant, workspace = await load_workspace(principal, session)
    await lock_workspace_settings(session, workspace)
    return await _publish(
        settings_document(workspace),
        principal,
        session,
        workspace,
        tenant.plan,
        payload.change_note,
        request=request,
    )


@router.post("/branding/rollback", response_model=BrandVersion)
async def rollback_branding(
    payload: RollbackRequest,
    request: Request,
    principal: BrandPublishPrincipal,
    session: DBSession,
) -> BrandVersion:
    _interactive_only(principal, "publication")
    tenant, workspace = await load_workspace(principal, session)
    await lock_workspace_settings(session, workspace)
    document = settings_document(workspace)
    source = next(
        (item for item in document.branding_versions if item.version == payload.version),
        None,
    )
    if source is None:
        raise HTTPException(status_code=404, detail="Brand version not found")
    document.branding_draft = source.branding.model_copy(deep=True)
    return await _publish(
        document,
        principal,
        session,
        workspace,
        tenant.plan,
        payload.change_note,
        request=request,
        action="workspace.brand.rollback",
    )
