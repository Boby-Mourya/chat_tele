from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import EmailStr, Field
from sqlalchemy import and_, func, select

from northstar_api.access_policy import effective_permissions
from northstar_api.branding_validation import normalize_raster
from northstar_api.dependencies import CurrentPrincipal, DBSession, require_permissions
from northstar_api.entitlements import entitlement_for_plan
from northstar_api.lead_crm.audit import record_audit_event
from northstar_api.models import (
    Role,
    Tenant,
    TenantMembership,
    User,
    Workspace,
    WorkspaceMembership,
    WorkspaceRole,
    WorkspaceStatus,
)
from northstar_api.modules.workspace.repositories.workspace_write_lock import lock_workspace_settings
from northstar_api.schemas import APIModel
from northstar_api.security import Principal
from northstar_api.services.outbox import enqueue_event
from northstar_api.workspace_contract import (
    WhiteLabelSettings,
    WhiteLabelWrite,
    WorkspacePreferences,
    WorkspaceSecurityPolicy,
    safe_legacy_read,
)
from northstar_api.workspace_invitations import WorkspaceInvitation

router = APIRouter(prefix="/workspace", tags=["workspace"])
collection_router = APIRouter(prefix="/workspaces", tags=["workspaces"])
WorkspaceViewPrincipal = Annotated[Principal, Depends(require_permissions("workspace.view"))]
WorkspaceUpdatePrincipal = Annotated[Principal, Depends(require_permissions("workspace.update"))]
WorkspaceMembersViewPrincipal = Annotated[Principal, Depends(require_permissions("members.view"))]
_image_slots = asyncio.Semaphore(2)


class WorkspaceOut(APIModel):
    id: str
    tenant_id: str
    tenant_name: str
    name: str
    slug: str
    status: WorkspaceStatus
    role: WorkspaceRole
    permissions: list[str]
    plan: str
    member_count: int
    preferences: WorkspacePreferences
    white_label: WhiteLabelSettings
    branding_published: bool = False
    branding_warnings: list[str] = Field(default_factory=list)
    education_create_upsell_leads: bool = False
    security: WorkspaceSecurityPolicy


class WorkspacePatch(APIModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    slug: str | None = Field(default=None, min_length=2, max_length=80, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    preferences: WorkspacePreferences | None = None
    white_label: WhiteLabelWrite | None = None
    education_create_upsell_leads: bool | None = None
    security: WorkspaceSecurityPolicy | None = None


class WorkspaceCreate(WorkspacePreferences):
    name: str = Field(min_length=2, max_length=160)
    slug: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class WorkspaceMemberOut(APIModel):
    id: str
    name: str
    email: EmailStr
    role: WorkspaceRole
    tenant_role: Role
    status: Literal["active"] = "active"


class WorkspaceInvitationOut(APIModel):
    id: str
    email: EmailStr
    role: WorkspaceRole
    status: Literal["invited"] = "invited"
    expires_at: datetime
    created_at: datetime


class WorkspaceTeamOut(APIModel):
    members: list[WorkspaceMemberOut]
    invitations: list[WorkspaceInvitationOut]


def _workspace_response(
    tenant: Tenant, workspace: Workspace, membership: WorkspaceMembership,
    member_count: int, tenant_role: Role = Role.MEMBER,
) -> WorkspaceOut:
    settings: dict[str, Any] = workspace.settings_json or {}
    warnings: list[str] = []
    brand = dict(workspace.branding_json or {})
    # Domain status is read-only here. Verification and activation are handled
    # by the dedicated domain lifecycle routes and worker.
    brand.setdefault("customDomain", "")
    brand.setdefault("dnsStatus", "not-configured")
    preferences = safe_legacy_read(WorkspacePreferences, {
        "timezone": workspace.timezone, "defaultLanguage": workspace.default_language,
        "dateFormat": workspace.date_format, **settings.get("preferences", {}),
    }, warnings)
    safe_brand = safe_legacy_read(WhiteLabelSettings, {"companyName": tenant.name, **brand}, warnings)
    security = safe_legacy_read(WorkspaceSecurityPolicy, settings.get("security", {}), warnings)
    return WorkspaceOut(
        id=str(workspace.id), tenant_id=str(tenant.id), tenant_name=tenant.name,
        name=workspace.name, slug=workspace.slug, status=workspace.status, role=membership.role,
        permissions=sorted(effective_permissions(tenant_role.value, membership.role.value)),
        plan=tenant.plan, member_count=member_count,
        preferences=WorkspacePreferences.model_validate(preferences.model_dump()),
        white_label=WhiteLabelSettings.model_validate(safe_brand.model_dump()),
        branding_published=bool(workspace.branding_json), branding_warnings=warnings,
        education_create_upsell_leads=False,
        security=security,
    )


async def _load_workspace(
    tenant_id: Any, workspace_id: UUID | None, user_id: UUID, session: DBSession,
) -> tuple[Tenant, Workspace, WorkspaceMembership, int]:
    row = (await session.execute(select(Tenant, Workspace, WorkspaceMembership)
        .join(Workspace, Workspace.tenant_id == Tenant.id)
        .join(WorkspaceMembership, WorkspaceMembership.workspace_id == Workspace.id)
        .where(Tenant.id == tenant_id, Workspace.id == workspace_id, WorkspaceMembership.user_id == user_id,
               WorkspaceMembership.tenant_id == tenant_id, Workspace.status == WorkspaceStatus.ACTIVE))).first()
    if not row:
        raise HTTPException(status_code=404, detail="Workspace not found")
    count = int(await session.scalar(select(func.count()).select_from(WorkspaceMembership).where(
        WorkspaceMembership.workspace_id == workspace_id, WorkspaceMembership.tenant_id == tenant_id,
    )) or 0)
    tenant, workspace, membership = row
    return tenant, workspace, membership, count


async def _team_response(tenant_id: UUID, workspace_id: UUID, session: DBSession) -> WorkspaceTeamOut:
    rows = (await session.execute(select(User, WorkspaceMembership, TenantMembership.role)
        .join(WorkspaceMembership, WorkspaceMembership.user_id == User.id)
        .join(TenantMembership, and_(TenantMembership.user_id == User.id, TenantMembership.tenant_id == WorkspaceMembership.tenant_id))
        .where(WorkspaceMembership.tenant_id == tenant_id, WorkspaceMembership.workspace_id == workspace_id, User.is_active.is_(True))
        .order_by(User.name, User.email))).all()
    invitations = list(await session.scalars(select(WorkspaceInvitation).where(
        WorkspaceInvitation.tenant_id == tenant_id, WorkspaceInvitation.workspace_id == workspace_id,
        WorkspaceInvitation.accepted_at.is_(None), WorkspaceInvitation.revoked_at.is_(None),
        WorkspaceInvitation.expires_at > datetime.now(UTC),
    ).order_by(WorkspaceInvitation.created_at.desc())))
    return WorkspaceTeamOut(
        members=[WorkspaceMemberOut(id=str(user.id), name=user.name, email=user.email, role=member.role, tenant_role=role)
                 for user, member, role in rows],
        invitations=[WorkspaceInvitationOut(id=str(value.id), email=value.email, role=value.role,
                                           expires_at=value.expires_at, created_at=value.created_at) for value in invitations],
    )


@router.get("", response_model=WorkspaceOut)
async def get_workspace(principal: WorkspaceViewPrincipal, session: DBSession) -> WorkspaceOut:
    return _workspace_response(*(await _load_workspace(principal.tenant_id, principal.workspace_id, principal.user_id, session)), tenant_role=principal.role)


@router.patch("", response_model=WorkspaceOut)
async def update_workspace(payload: WorkspacePatch, principal: WorkspaceUpdatePrincipal, session: DBSession) -> WorkspaceOut:
    tenant, workspace, membership, count = await _load_workspace(principal.tenant_id, principal.workspace_id, principal.user_id, session)
    # Match the section-23 settings writers: reload under a PostgreSQL row lock
    # before changing any field in the shared settings_json or branding_json.
    await lock_workspace_settings(session, workspace)
    if payload.slug and payload.slug != workspace.slug:
        duplicate = await session.scalar(select(Workspace.id).where(
            Workspace.tenant_id == principal.tenant_id, Workspace.slug == payload.slug, Workspace.id != workspace.id,
        ))
        if duplicate:
            raise HTTPException(status_code=409, detail="Workspace slug is already in use")
        workspace.slug = payload.slug
    if payload.name is not None:
        workspace.name = payload.name.strip()
    settings = dict(workspace.settings_json or {})
    if payload.preferences is not None:
        settings["preferences"] = payload.preferences.model_dump(by_alias=True)
        workspace.timezone = payload.preferences.timezone
        workspace.default_language = payload.preferences.default_language
        workspace.date_format = payload.preferences.date_format
    if payload.white_label is not None:
        if not principal.can("branding.publish") or principal.token_id.startswith("api_key:"):
            raise HTTPException(status_code=403, detail="Interactive branding publication permission required")
        brand = payload.white_label.model_dump(by_alias=True, mode="json")
        policy = entitlement_for_plan(tenant.plan)
        if not policy.white_label_enabled:
            raise HTTPException(status_code=403, detail="White label branding is not available on your plan")
        previous = workspace.branding_json or {}
        for field, included in (("brandedEmails", policy.branded_email_enabled), ("removePlatformBranding", policy.remove_platform_mark_enabled)):
            if brand[field] and not previous.get(field, False) and not included:
                raise HTTPException(status_code=403, detail=f"Your plan does not include {field}")
        try:
            async with _image_slots:
                for field in ("logoDataUrl", "faviconDataUrl", "appIconDataUrl"):
                    brand[field] = await asyncio.to_thread(normalize_raster, str(brand[field]))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        # Legacy clients may submit customDomain/dnsStatus. Preserve the
        # hostname for display, but never let a legacy write mark a domain as
        # verified or active; that requires the dedicated DNS/TLS lifecycle.
        legacy_status = str(brand.get("dnsStatus", "not-configured"))
        if legacy_status not in {"not-configured", "pending", "dns_pending"}:
            legacy_status = "not-configured"
        workspace.branding_json = {
            **brand,
            "customDomain": str(brand.get("customDomain", previous.get("customDomain", ""))),
            "dnsStatus": legacy_status,
        }
        record_audit_event(session, tenant_id=principal.tenant_id, workspace_id=workspace.id, actor_user_id=principal.user_id,
                           action="workspace.branding.updated", entity_type="workspace", entity_id=str(workspace.id), category="workspace",
                           metadata={"fields": sorted(brand)})
        enqueue_event(session, tenant_id=principal.tenant_id, aggregate_type="workspace", aggregate_id=workspace.id,
                      event_type="workspace.branding.updated.v1", payload={"workspaceId": str(workspace.id)})
    if payload.education_create_upsell_leads:
        raise HTTPException(status_code=409, detail="Education chats stay separate from leads")
    if payload.education_create_upsell_leads is not None:
        settings["educationCreateUpsellLeads"] = False
    if payload.security is not None:
        settings["security"] = payload.security.model_dump(by_alias=True, mode="json")
        record_audit_event(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=workspace.id,
            actor_user_id=principal.user_id,
            action="workspace.security.updated",
            entity_type="workspace",
            entity_id=str(workspace.id),
            category="security",
            metadata={"fields": sorted(payload.security.model_fields_set)},
        )
        enqueue_event(
            session,
            tenant_id=principal.tenant_id,
            aggregate_type="workspace",
            aggregate_id=workspace.id,
            event_type="workspace.security.updated.v1",
            payload={"workspaceId": str(workspace.id)},
        )
    workspace.settings_json = settings
    await session.commit()
    await session.refresh(workspace)
    return _workspace_response(tenant, workspace, membership, count, principal.role)


@router.get("/team", response_model=WorkspaceTeamOut)
async def get_workspace_team(principal: WorkspaceMembersViewPrincipal, session: DBSession) -> WorkspaceTeamOut:
    _, workspace, _, _ = await _load_workspace(principal.tenant_id, principal.workspace_id, principal.user_id, session)
    return await _team_response(principal.tenant_id, workspace.id, session)


@collection_router.get("", response_model=list[WorkspaceOut])
async def list_workspaces(principal: CurrentPrincipal, session: DBSession) -> list[WorkspaceOut]:
    query = select(Tenant, Workspace, WorkspaceMembership).join(Workspace, Workspace.tenant_id == Tenant.id).join(
        WorkspaceMembership, WorkspaceMembership.workspace_id == Workspace.id,
    ).where(Tenant.id == principal.tenant_id, WorkspaceMembership.user_id == principal.user_id,
            WorkspaceMembership.tenant_id == principal.tenant_id, Workspace.status == WorkspaceStatus.ACTIVE)
    if principal.token_id.startswith("api_key:"):
        query = query.where(Workspace.id == principal.workspace_id)
    results = []
    for tenant, workspace, membership in (await session.execute(query.order_by(Workspace.name, Workspace.id))).all():
        count = int(await session.scalar(select(func.count()).select_from(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace.id, WorkspaceMembership.tenant_id == principal.tenant_id,
        )) or 0)
        results.append(_workspace_response(tenant, workspace, membership, count, principal.role))
    return results


@collection_router.post("", response_model=WorkspaceOut, status_code=201)
async def create_workspace(payload: WorkspaceCreate, principal: CurrentPrincipal, session: DBSession) -> WorkspaceOut:
    if not principal.can("workspace.create"):
        raise HTTPException(status_code=403, detail="Organization workspace creation permission required")
    if await session.scalar(select(Workspace.id).where(Workspace.tenant_id == principal.tenant_id, Workspace.slug == payload.slug)):
        raise HTTPException(status_code=409, detail="Workspace slug is already in use")
    tenant = await session.scalar(select(Tenant).where(Tenant.id == principal.tenant_id))
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    workspace = Workspace(tenant_id=principal.tenant_id, name=payload.name.strip(), slug=payload.slug,
                          timezone=payload.timezone, default_language=payload.default_language, date_format=payload.date_format,
                          created_by=principal.user_id)
    session.add(workspace)
    await session.flush()
    membership = WorkspaceMembership(workspace_id=workspace.id, user_id=principal.user_id, tenant_id=principal.tenant_id,
                                     role=WorkspaceRole.ADMIN, all_agents_access=True)
    session.add(membership)
    await session.commit()
    await session.refresh(workspace)
    return _workspace_response(tenant, workspace, membership, 1, principal.role)


@collection_router.get("/{workspace_id}", response_model=WorkspaceOut)
async def get_workspace_by_id(workspace_id: UUID, principal: WorkspaceViewPrincipal, session: DBSession) -> WorkspaceOut:
    if principal.token_id.startswith("api_key:") and workspace_id != principal.workspace_id:
        raise HTTPException(status_code=403, detail="API key is scoped to a different workspace")
    return _workspace_response(*(await _load_workspace(principal.tenant_id, workspace_id, principal.user_id, session)), tenant_role=principal.role)
