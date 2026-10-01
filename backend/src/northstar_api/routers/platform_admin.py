from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from redis.exceptions import RedisError
from sqlalchemy import select

from northstar_api.config import get_settings
from northstar_api.dependencies import CurrentPrincipal, DBSession
from northstar_api.entitlements import PLAN_ENTITLEMENTS
from northstar_api.lead_crm.audit import record_audit_event
from northstar_api.models import (
    PlatformAdminAssignment,
    Tenant,
    TenantMembership,
    User,
    Workspace,
    WorkspaceMembership,
    WorkspaceStatus,
)
from northstar_api.modules.platform_admin.access import (
    PLATFORM_PERMISSIONS,
    platform_admin_emails,
    platform_admin_permissions,
    platform_role_permissions,
)
from northstar_api.platform_admin_schemas import (
    PlatformAdminAccessOut,
    PlatformOperatorOut,
    PlatformOperatorPatch,
    PlatformConfigurationOut,
    PlatformEntitlementOut,
    PlatformImpersonationEnd,
    PlatformImpersonationOut,
    PlatformImpersonationRequest,
    PlatformOperationsOut,
    PlatformOverviewOut,
    PlatformTenantDetailOut,
    PlatformTenantListOut,
    PlatformTenantLifecyclePatch,
    PlatformTenantSubscriptionPatch,
)
from northstar_api.security import Principal, create_access_token
from northstar_api.services.password_reset import credential_version
from northstar_api.services.platform_admin import (
    get_platform_tenant,
    list_platform_tenants,
    platform_overview,
)
from northstar_api.services.rate_limit import redis_services
from northstar_api.services.subscriptions import SubscriptionError, set_subscription_state
from northstar_api.subscriptions import SubscriptionStatus

router = APIRouter(prefix="/platform-admin", tags=["platform admin"])


async def require_platform_admin(
    principal: CurrentPrincipal,
    session: DBSession,
) -> Principal:
    if principal.token_id.startswith("api_key:"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API keys cannot access the platform control plane",
        )
    email = await session.scalar(
        select(User.email).where(
            User.id == principal.user_id,
            User.is_active.is_(True),
        )
    )
    assignment = await session.get(PlatformAdminAssignment, principal.user_id)
    env_allowed = platform_admin_emails()
    assignment_active = assignment is not None and assignment.is_active and assignment.revoked_at is None
    if email is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform administrator access required",
        )
    if not assignment_active and email.strip().lower() not in env_allowed:
        detail = (
            "Platform administration is not enabled for this account"
            if not env_allowed
            else "Platform administrator access required"
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
    return principal


PlatformAdminPrincipal = Annotated[Principal, Depends(require_platform_admin)]


def require_platform_permissions(*required: str):
    async def dependency(principal: CurrentPrincipal, session: DBSession) -> Principal:
        checked = await require_platform_admin(principal, session)
        if not set(required) <= await _resolved_platform_permissions(session, checked):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Platform administrator capability required",
            )
        return checked

    return dependency


PlatformOverviewPrincipal = Annotated[
    Principal, Depends(require_platform_permissions("platform.overview.read"))
]
PlatformTenantsReadPrincipal = Annotated[
    Principal, Depends(require_platform_permissions("platform.tenants.read"))
]
PlatformTenantsManagePrincipal = Annotated[
    Principal, Depends(require_platform_permissions("platform.tenants.manage"))
]
PlatformBillingManagePrincipal = Annotated[
    Principal, Depends(require_platform_permissions("platform.billing.manage"))
]
PlatformSupportPrincipal = Annotated[
    Principal, Depends(require_platform_permissions("platform.support.impersonate"))
]
PlatformSystemReadPrincipal = Annotated[
    Principal, Depends(require_platform_permissions("platform.system.read"))
]
PlatformAdminsManagePrincipal = Annotated[
    Principal, Depends(require_platform_permissions("platform.admins.manage"))
]


async def _resolved_platform_permissions(session: DBSession, principal: Principal) -> frozenset[str]:
    assignment = await session.get(PlatformAdminAssignment, principal.user_id)
    if assignment is not None and assignment.is_active and assignment.revoked_at is None:
        configured = (assignment.permissions_json or {}).get("permissions")
        return platform_role_permissions(assignment.role, configured)
    email = await session.scalar(select(User.email).where(User.id == principal.user_id))
    return platform_admin_permissions(email or "")


async def _platform_admin_email(session: DBSession, principal: Principal) -> str:
    value = await session.scalar(select(User.email).where(User.id == principal.user_id))
    if value is None:
        raise HTTPException(status_code=401, detail="Account is unavailable")
    return value


@router.get("/access", response_model=PlatformAdminAccessOut)
async def get_platform_admin_access(
    principal: PlatformAdminPrincipal,
    session: DBSession,
) -> PlatformAdminAccessOut:
    return PlatformAdminAccessOut(
        authorized=True,
        email=await _platform_admin_email(session, principal),
    )


@router.get("/permissions")
async def get_platform_admin_permissions(
    principal: PlatformAdminPrincipal,
    session: DBSession,
) -> dict[str, object]:
    email = await _platform_admin_email(session, principal)
    return {"email": email, "permissions": sorted(await _resolved_platform_permissions(session, principal))}


@router.get("/operators", response_model=list[PlatformOperatorOut])
async def list_platform_operators(
    _: PlatformSystemReadPrincipal,
    session: DBSession,
) -> list[PlatformOperatorOut]:
    rows = list(
        (await session.execute(
            select(PlatformAdminAssignment, User)
            .join(User, User.id == PlatformAdminAssignment.user_id)
            .order_by(User.email)
        )).all()
    )
    return [
        PlatformOperatorOut(
            user_id=user.id,
            name=user.name,
            email=user.email,
            role=assignment.role,
            permissions=sorted(platform_role_permissions(
                assignment.role, (assignment.permissions_json or {}).get("permissions")
            )),
            is_active=assignment.is_active and assignment.revoked_at is None,
            created_at=assignment.created_at,
        )
        for assignment, user in rows
    ]


@router.put("/operators/{user_id}", response_model=PlatformOperatorOut)
async def update_platform_operator(
    user_id: UUID,
    payload: PlatformOperatorPatch,
    principal: PlatformAdminsManagePrincipal,
    session: DBSession,
) -> PlatformOperatorOut:
    target = await session.scalar(select(User).where(User.id == user_id))
    if target is None:
        raise HTTPException(status_code=404, detail="Platform operator account not found")
    unknown = set(payload.permissions) - PLATFORM_PERMISSIONS
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown platform permissions: {sorted(unknown)}")
    assignment = await session.get(PlatformAdminAssignment, user_id)
    if assignment is None:
        assignment = PlatformAdminAssignment(user_id=user_id, created_by_user_id=principal.user_id)
        session.add(assignment)
    assignment.role = payload.role
    assignment.permissions_json = {"permissions": sorted(set(payload.permissions))}
    assignment.is_active = payload.is_active
    assignment.revoked_at = None if payload.is_active else datetime.now(UTC)
    record_audit_event(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=None,
        actor_user_id=principal.user_id,
        action="platform.admin.assignment.updated",
        entity_type="platform_admin_assignment",
        entity_id=str(user_id),
        category="security",
        severity="warning",
        after={"role": payload.role, "isActive": payload.is_active, "permissions": sorted(set(payload.permissions))},
        metadata={"reason": payload.reason},
    )
    await session.commit()
    return PlatformOperatorOut(
        user_id=target.id,
        name=target.name,
        email=target.email,
        role=assignment.role,
        permissions=sorted(platform_role_permissions(assignment.role, payload.permissions)),
        is_active=assignment.is_active and assignment.revoked_at is None,
        created_at=assignment.created_at,
    )


@router.get("/overview", response_model=PlatformOverviewOut)
@router.get("/dashboard", response_model=PlatformOverviewOut)
@router.get("/usage", response_model=PlatformOverviewOut)
async def get_platform_overview(
    _: PlatformOverviewPrincipal,
    session: DBSession,
) -> PlatformOverviewOut:
    return await platform_overview(session)


@router.get("/health", response_model=PlatformOperationsOut)
async def get_platform_health(
    _: PlatformOverviewPrincipal,
    session: DBSession,
) -> PlatformOperationsOut:
    """Expose the operational health slice for the dedicated health route."""
    return (await platform_overview(session)).operations


@router.get("/entitlements", response_model=list[PlatformEntitlementOut])
@router.get("/plans", response_model=list[PlatformEntitlementOut])
async def get_platform_entitlements(_: PlatformSystemReadPrincipal) -> list[PlatformEntitlementOut]:
    """Expose the server-owned plan catalog to platform operators."""
    return [
        PlatformEntitlementOut(
            plan=plan,
            workspace_limit=value.workspace_limit,
            agent_limit=value.agent_limit,
            member_limit=value.member_limit,
            conversation_limit_monthly=value.conversation_limit_monthly,
            token_limit_monthly=value.token_limit_monthly,
            storage_limit_bytes=value.storage_limit_bytes,
            allowed_channels=sorted(value.allowed_channels),
            crm_enabled=value.crm_enabled,
            api_enabled=value.api_enabled,
            white_label_enabled=value.white_label_enabled,
            custom_domain_enabled=value.custom_domain_enabled,
            branded_email_enabled=value.branded_email_enabled,
            remove_platform_mark_enabled=value.remove_platform_mark_enabled,
        )
        for plan, value in PLAN_ENTITLEMENTS.items()
    ]


@router.get("/configuration", response_model=PlatformConfigurationOut)
@router.get("/system", response_model=PlatformConfigurationOut)
async def get_platform_configuration(_: PlatformSystemReadPrincipal) -> PlatformConfigurationOut:
    """Expose non-secret runtime flags and limits to platform operators."""
    settings = get_settings()
    return PlatformConfigurationOut(
        app_env=settings.app_env,
        app_api_prefix=settings.app_api_prefix,
        background_dispatch_enabled=settings.background_dispatch_enabled,
        kafka_enabled=settings.kafka_enabled,
        education_multi_course_enabled=settings.education_multi_course_enabled,
        require_nvidia=settings.require_nvidia,
        allow_deterministic_embeddings=settings.allow_deterministic_embeddings,
        platform_impersonation_ttl_minutes=settings.platform_impersonation_ttl_minutes,
        rate_limit_fail_open=settings.rate_limit_fail_open,
        retrieval_candidate_limit=settings.retrieval_candidate_limit,
        retrieval_context_limit=settings.retrieval_context_limit,
        knowledge_max_pdf_pages=settings.knowledge_max_pdf_pages,
        knowledge_max_chunks=settings.knowledge_max_chunks,
    )


@router.get("/tenants", response_model=PlatformTenantListOut)
async def get_platform_tenants(
    _: PlatformTenantsReadPrincipal,
    session: DBSession,
    search: str | None = Query(default=None, max_length=160),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> PlatformTenantListOut:
    return await list_platform_tenants(
        session,
        search=search,
        limit=limit,
        offset=offset,
    )


@router.get("/tenants/{tenant_id}", response_model=PlatformTenantDetailOut)
async def get_platform_tenant_detail(
    tenant_id: UUID,
    _: PlatformTenantsReadPrincipal,
    session: DBSession,
) -> PlatformTenantDetailOut:
    value = await get_platform_tenant(session, tenant_id=tenant_id)
    if value is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return value


@router.patch("/tenants/{tenant_id}/subscription", response_model=PlatformTenantDetailOut)
async def update_platform_tenant_subscription(
    tenant_id: UUID,
    payload: PlatformTenantSubscriptionPatch,
    principal: PlatformBillingManagePrincipal,
    session: DBSession,
) -> PlatformTenantDetailOut:
    """Apply a support override with an explicit reason and durable audit event."""
    try:
        subscription = await set_subscription_state(
            session,
            tenant_id=tenant_id,
            plan=payload.plan,
            status=SubscriptionStatus(payload.status) if payload.status else None,
        )
    except (SubscriptionError, ValueError) as exc:
        raise HTTPException(status_code=getattr(exc, "status_code", 422), detail=str(exc)) from exc
    record_audit_event(
        session,
        tenant_id=tenant_id,
        workspace_id=None,
        actor_user_id=principal.user_id,
        action="platform.tenant.subscription.updated",
        entity_type="tenant_subscription",
        entity_id=str(subscription.id),
        category="billing",
        severity="warning",
        after={"plan": subscription.plan, "status": subscription.status.value},
        metadata={"reason": payload.reason},
    )
    await session.commit()
    value = await get_platform_tenant(session, tenant_id=tenant_id)
    if value is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return value


@router.patch("/tenants/{tenant_id}/lifecycle", response_model=PlatformTenantDetailOut)
async def update_platform_tenant_lifecycle(
    tenant_id: UUID,
    payload: PlatformTenantLifecyclePatch,
    principal: PlatformTenantsManagePrincipal,
    session: DBSession,
) -> PlatformTenantDetailOut:
    """Suspend/reactivate a tenant without deleting data or losing prior state."""
    tenant = await session.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    workspaces = list(
        await session.scalars(select(Workspace).where(Workspace.tenant_id == tenant_id).with_for_update())
    )
    settings = dict(tenant.settings_json or {})
    suspended_ids = [str(item) for item in settings.get("platformSuspendedWorkspaceIds", []) if isinstance(item, str)]
    if payload.action == "suspend":
        newly_archived = [str(workspace.id) for workspace in workspaces if workspace.status == WorkspaceStatus.ACTIVE]
        for workspace in workspaces:
            if workspace.status == WorkspaceStatus.ACTIVE:
                workspace.status = WorkspaceStatus.ARCHIVED
                workspace.archived_at = datetime.now(UTC)
        settings["platformSuspendedWorkspaceIds"] = sorted(set(suspended_ids + newly_archived))
    else:
        restore = set(suspended_ids)
        for workspace in workspaces:
            if str(workspace.id) in restore and workspace.status == WorkspaceStatus.ARCHIVED:
                workspace.status = WorkspaceStatus.ACTIVE
                workspace.archived_at = None
        settings.pop("platformSuspendedWorkspaceIds", None)
    tenant.settings_json = settings
    record_audit_event(
        session,
        tenant_id=tenant_id,
        workspace_id=None,
        actor_user_id=principal.user_id,
        action=f"platform.tenant.{payload.action}",
        entity_type="tenant",
        entity_id=str(tenant_id),
        category="security",
        severity="warning",
        after={"action": payload.action, "workspaceCount": len(workspaces)},
        metadata={"reason": payload.reason},
    )
    await session.commit()
    value = await get_platform_tenant(session, tenant_id=tenant_id)
    if value is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return value


@router.post("/impersonation", response_model=PlatformImpersonationOut)
async def start_platform_impersonation(
    payload: PlatformImpersonationRequest,
    principal: PlatformSupportPrincipal,
    session: DBSession,
) -> PlatformImpersonationOut:
    """Issue a short-lived, explicitly tagged support session without a password."""
    membership = await session.scalar(
        select(TenantMembership).where(
            TenantMembership.tenant_id == payload.tenant_id,
            TenantMembership.user_id == payload.user_id,
        )
    )
    workspace_membership = await session.scalar(
        select(WorkspaceMembership)
        .join(Workspace, Workspace.id == WorkspaceMembership.workspace_id)
        .where(
            WorkspaceMembership.tenant_id == payload.tenant_id,
            WorkspaceMembership.workspace_id == payload.workspace_id,
            WorkspaceMembership.user_id == payload.user_id,
            Workspace.status == WorkspaceStatus.ACTIVE,
        )
    )
    if membership is None or workspace_membership is None:
        raise HTTPException(status_code=404, detail="Target workspace membership not found")
    target = await session.scalar(select(User).where(User.id == payload.user_id, User.is_active.is_(True)))
    if target is None:
        raise HTTPException(status_code=404, detail="Target user not found")
    impersonation_id = f"imp_{secrets.token_urlsafe(18)}"
    access_token, expires_at = create_access_token(
        target.id,
        payload.tenant_id,
        membership.role,
        credential_version=await credential_version(session, target.id),
        platform_actor_id=principal.user_id,
        impersonation_id=impersonation_id,
        ttl_minutes=get_settings().platform_impersonation_ttl_minutes,
    )
    record_audit_event(
        session,
        tenant_id=payload.tenant_id,
        workspace_id=payload.workspace_id,
        actor_user_id=principal.user_id,
        action="platform.impersonation.started",
        entity_type="user",
        entity_id=str(target.id),
        category="security",
        severity="warning",
        after={"impersonationId": impersonation_id, "actingAsUserId": str(target.id)},
        metadata={"reason": payload.reason},
    )
    await session.commit()
    return PlatformImpersonationOut(
        access_token=access_token,
        expires_at=expires_at,
        tenant_id=payload.tenant_id,
        workspace_id=payload.workspace_id,
        user_id=target.id,
        impersonation_id=impersonation_id,
    )


@router.post("/impersonation/{impersonation_id}/end", status_code=status.HTTP_204_NO_CONTENT)
async def end_platform_impersonation(
    impersonation_id: str,
    payload: PlatformImpersonationEnd,
    principal: CurrentPrincipal,
    session: DBSession,
) -> None:
    if not impersonation_id.startswith("imp_"):
        raise HTTPException(status_code=404, detail="Support session not found")
    if principal.impersonation_id != impersonation_id:
        await require_platform_admin(principal, session)
    try:
        await redis_services.client.set(
            f"northstar:impersonation:revoked:{impersonation_id}", "1", ex=86_400
        )
    except RedisError as exc:
        raise HTTPException(status_code=503, detail="Session service unavailable") from exc
    record_audit_event(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=None,
        actor_user_id=principal.platform_actor_id or principal.user_id,
        action="platform.impersonation.ended",
        entity_type="support_session",
        entity_id=impersonation_id,
        category="security",
        severity="warning",
        metadata={"reason": payload.reason},
    )
    await session.commit()
