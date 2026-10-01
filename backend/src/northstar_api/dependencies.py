from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.config import get_settings
from northstar_api.database import get_session, set_tenant_context
from northstar_api.models import (
    Role,
    TenantMembership,
    User,
    Workspace,
    WorkspaceMemberAgentAccess,
    WorkspaceMembership,
    WorkspaceRole,
    WorkspaceStatus,
)
from northstar_api.modules.workspace.api_key_scopes import permissions_for_api_key_scopes
from northstar_api.modules.workspace.contracts import WorkspaceSettingsBundle
from northstar_api.modules.workspace.conversation_scope import set_conversation_assignment_scope
from northstar_api.modules.workspace.member_state import is_member_suspended
from northstar_api.modules.workspace.security_policy import (
    enforce_network_security,
    enforce_request_security,
)
from northstar_api.onboarding_models import OrganizationSetup
from northstar_api.security import (
    TENANT_ROLE_PERMISSIONS,
    WORKSPACE_ROLE_PERMISSIONS,
    Principal,
    decode_token,
)
from northstar_api.services.email_verification import email_is_verified
from northstar_api.services.password_reset import credential_version
from northstar_api.services.rate_limit import redis_services
from northstar_api.services.workspace_api_keys import find_active_workspace_api_key

bearer = HTTPBearer(auto_error=False)
DBSession = Annotated[AsyncSession, Depends(get_session)]


async def get_current_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    session: DBSession,
) -> Principal:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Authentication required")
    token = credentials.credentials
    if token.startswith("nsk_live_"):
        principal = await authenticate_api_key(token, session, request=request)
    else:
        principal = await authenticate_access_token(token, session, request=request)
    request.state.principal = principal
    path = request.url.path.removeprefix(get_settings().app_api_prefix.rstrip("/"))
    if path.startswith("/v1/"):
        path = path[3:]
    setup_paths = {"/bootstrap", "/onboarding", "/workspaces", "/workspace"}
    setup = await session.scalar(
        select(OrganizationSetup).where(OrganizationSetup.tenant_id == principal.tenant_id)
    )
    if setup is not None and setup.required and not setup.profile_complete:
        safe_read = request.method in {"GET", "HEAD"} and (
            path in setup_paths or path.startswith("/platform-admin")
        )
        if not safe_read and not path.startswith(("/auth/", "/organization/", "/billing/", "/platform-admin")):
            raise HTTPException(
                status_code=428,
                detail="Complete your organization profile before using workspace resources",
            )
    return principal


async def _agent_scope(
    session: AsyncSession,
    membership: WorkspaceMembership,
    user_id: UUID,
) -> frozenset[UUID] | None:
    if membership.all_agents_access:
        return None
    return frozenset(
        await session.scalars(
            select(WorkspaceMemberAgentAccess.agent_id).where(
                WorkspaceMemberAgentAccess.workspace_id == membership.workspace_id,
                WorkspaceMemberAgentAccess.user_id == user_id,
            )
        )
    )


def _workspace_settings(workspace: Workspace) -> WorkspaceSettingsBundle:
    raw = dict(workspace.settings_json or {}).get("workspaceSettingsV2", {})
    try:
        return WorkspaceSettingsBundle.model_validate(raw)
    except (TypeError, ValueError):
        return WorkspaceSettingsBundle()


def _custom_role_context(
    workspace: Workspace,
    user_id: UUID,
) -> tuple[frozenset[str], frozenset[UUID] | None, bool, frozenset[str]]:
    settings = _workspace_settings(workspace)
    assigned = set(settings.roles.member_role_ids.get(str(user_id), []))
    roles = [role for role in settings.roles.custom_roles if role.id in assigned]
    permissions = frozenset(
        permission for role in roles for permission in role.permissions
    )

    scopes: list[set[UUID]] = []
    selected_agent_ids: set[UUID] = set()
    selected_agents_declared = False
    for role in roles:
        if "agents" in role.resources.selected:
            selected_agents_declared = True
            for value in role.resources.selected.get("agents", []):
                try:
                    selected_agent_ids.add(UUID(value))
                except ValueError:
                    continue
    if selected_agents_declared:
        scopes.append(selected_agent_ids)

    conversation_scopes = {
        role.resources.conversation_scope for role in roles
    }
    team_ids: set[str] = set()
    if "all" not in conversation_scopes and "team" in conversation_scopes:
        team_agent_ids: set[UUID] = set()
        user_key = str(user_id)
        for team in settings.teams.teams:
            if user_key not in set(team.member_ids) | set(team.manager_ids):
                continue
            team_ids.add(team.id)
            for value in team.agent_ids:
                try:
                    team_agent_ids.add(UUID(value))
                except ValueError:
                    continue
        scopes.append(team_agent_ids)

    custom_agent_scope: frozenset[UUID] | None = None
    if scopes:
        effective = scopes[0]
        for scope in scopes[1:]:
            effective &= scope
        custom_agent_scope = frozenset(effective)

    assigned_conversations_only = (
        "assigned" in conversation_scopes
        and "team" not in conversation_scopes
        and "all" not in conversation_scopes
    )
    return (
        permissions,
        custom_agent_scope,
        assigned_conversations_only,
        frozenset(team_ids),
    )


def _merge_agent_scope(
    membership_scope: frozenset[UUID] | None,
    custom_scope: frozenset[UUID] | None,
) -> frozenset[UUID] | None:
    if custom_scope is None:
        return membership_scope
    if membership_scope is None:
        return custom_scope
    return membership_scope & custom_scope


async def authenticate_api_key(
    token: str,
    session: AsyncSession,
    *,
    request: Request | None = None,
) -> Principal:
    api_key = await find_active_workspace_api_key(session, token)
    if api_key is None or api_key.created_by_user_id is None:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")
    tenant_membership = await session.scalar(
        select(TenantMembership)
        .join(User, User.id == TenantMembership.user_id)
        .where(
            TenantMembership.user_id == api_key.created_by_user_id,
            TenantMembership.tenant_id == api_key.tenant_id,
            User.is_active.is_(True),
        )
    )
    workspace_membership = await session.scalar(
        select(WorkspaceMembership)
        .join(Workspace, Workspace.id == WorkspaceMembership.workspace_id)
        .where(
            WorkspaceMembership.user_id == api_key.created_by_user_id,
            WorkspaceMembership.tenant_id == api_key.tenant_id,
            WorkspaceMembership.workspace_id == api_key.workspace_id,
            Workspace.status == WorkspaceStatus.ACTIVE,
            Workspace.tenant_id == api_key.tenant_id,
        )
    )
    workspace = await session.scalar(
        select(Workspace).where(
            Workspace.id == api_key.workspace_id,
            Workspace.tenant_id == api_key.tenant_id,
            Workspace.status == WorkspaceStatus.ACTIVE,
        )
    )
    if tenant_membership is None or workspace_membership is None or workspace is None:
        raise HTTPException(status_code=401, detail="API key access is unavailable")
    if is_member_suspended(workspace.settings_json, api_key.created_by_user_id):
        raise HTTPException(status_code=403, detail="Workspace membership is suspended")
    enforce_network_security(workspace, request)
    if not await email_is_verified(session, api_key.created_by_user_id):
        raise HTTPException(status_code=403, detail="Email verification required")
    requested_workspace = request.headers.get("x-workspace-id", "").strip() if request else ""
    if requested_workspace:
        try:
            requested_workspace_id = UUID(requested_workspace)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid workspace identifier") from None
        if requested_workspace_id != api_key.workspace_id:
            raise HTTPException(status_code=403, detail="API key is scoped to a different workspace")
    api_key.last_used_at = datetime.now(UTC)
    await session.commit()
    await set_tenant_context(session, api_key.tenant_id)
    set_conversation_assignment_scope(session)
    service_workspace_role = (
        WorkspaceRole.MANAGER
        if workspace_membership.role == WorkspaceRole.ADMIN
        else workspace_membership.role
    )
    role_permissions = WORKSPACE_ROLE_PERMISSIONS[service_workspace_role]
    scoped_permissions = permissions_for_api_key_scopes(list(api_key.scopes or []))
    return Principal(
        user_id=api_key.created_by_user_id,
        tenant_id=api_key.tenant_id,
        role=Role.MEMBER,
        token_id=f"api_key:{api_key.id}",
        workspace_id=api_key.workspace_id,
        workspace_role=service_workspace_role,
        permissions=role_permissions & scoped_permissions,
        agent_ids=await _agent_scope(
            session,
            workspace_membership,
            api_key.created_by_user_id,
        ),
    )


def _allows_organization_context(request: Request | None) -> bool:
    if request is None:
        return False
    path = request.url.path.removeprefix(get_settings().app_api_prefix.rstrip("/"))
    if path.startswith("/v1/"):
        path = path[3:]
    return path in {
        "/bootstrap",
        "/onboarding",
        "/workspaces",
        "/auth/logout",
        "/me/organizations",
        "/auth/select-organization",
    } or path.startswith(("/billing/", "/organization/", "/platform-admin"))


async def authenticate_access_token(
    token: str,
    session: AsyncSession,
    *,
    request: Request | None = None,
) -> Principal:
    try:
        payload = decode_token(token, "access")
        user_id = UUID(payload["sub"])
        tenant_id = UUID(payload["tid"])
        token_role = Role(payload["role"])
    except (ValueError, KeyError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid or expired access token") from None
    try:
        if await redis_services.client.exists(f"northstar:revoked:{payload['jti']}"):
            raise HTTPException(status_code=401, detail="Access token was revoked")
        if payload.get("impersonationId") and await redis_services.client.exists(
            f"northstar:impersonation:revoked:{payload['impersonationId']}"
        ):
            raise HTTPException(status_code=401, detail="Support session has ended")
    except RedisError:
        if not redis_services.settings.rate_limit_fail_open:
            raise HTTPException(status_code=503, detail="Session service unavailable") from None
    membership = await session.scalar(
        select(TenantMembership)
        .join(User, User.id == TenantMembership.user_id)
        .where(
            TenantMembership.user_id == user_id,
            TenantMembership.tenant_id == tenant_id,
            User.is_active.is_(True),
        )
    )
    if not membership:
        raise HTTPException(status_code=401, detail="Account or workspace is unavailable")
    if membership.role != token_role:
        raise HTTPException(status_code=401, detail="Session role is stale; sign in again")
    if int(payload.get("cv", 0)) != await credential_version(session, user_id):
        raise HTTPException(status_code=401, detail="Session credentials changed; sign in again")
    allow_unverified_logout = bool(request and request.url.path.endswith("/auth/logout"))
    if not allow_unverified_logout and not await email_is_verified(session, user_id):
        raise HTTPException(status_code=403, detail="Email verification required")
    await set_tenant_context(session, tenant_id)
    requested_workspace = request.headers.get("x-workspace-id", "").strip() if request else ""
    workspace_id: UUID | None = None
    if requested_workspace:
        try:
            workspace_id = UUID(requested_workspace)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid workspace identifier") from None
    query = (
        select(WorkspaceMembership)
        .join(Workspace, Workspace.id == WorkspaceMembership.workspace_id)
        .where(
            WorkspaceMembership.user_id == user_id,
            WorkspaceMembership.tenant_id == tenant_id,
            Workspace.tenant_id == tenant_id,
            Workspace.status == WorkspaceStatus.ACTIVE,
        )
        .order_by(WorkspaceMembership.created_at, WorkspaceMembership.workspace_id)
    )
    if workspace_id:
        query = query.where(WorkspaceMembership.workspace_id == workspace_id)
    workspace_membership = await session.scalar(query)
    if not workspace_membership:
        if workspace_id is not None or not _allows_organization_context(request):
            raise HTTPException(status_code=403, detail="Workspace access is unavailable")
        set_conversation_assignment_scope(session)
        return Principal(
            user_id=user_id,
            tenant_id=tenant_id,
            role=membership.role,
            token_id=payload["jti"],
            permissions=TENANT_ROLE_PERMISSIONS[membership.role],
            platform_actor_id=UUID(payload["platformActorId"]) if payload.get("platformActorId") else None,
            impersonation_id=str(payload["impersonationId"]) if payload.get("impersonationId") else None,
        )
    workspace = await session.scalar(
        select(Workspace).where(
            Workspace.id == workspace_membership.workspace_id,
            Workspace.tenant_id == tenant_id,
            Workspace.status == WorkspaceStatus.ACTIVE,
        )
    )
    user = await session.scalar(
        select(User).where(User.id == user_id, User.is_active.is_(True))
    )
    if workspace is None or user is None:
        raise HTTPException(status_code=403, detail="Workspace access is unavailable")
    if is_member_suspended(workspace.settings_json, user_id):
        raise HTTPException(status_code=403, detail="Workspace membership is suspended")
    enforce_request_security(workspace, user, workspace_membership.role, payload, request)
    (
        custom_permissions,
        custom_agent_scope,
        assigned_conversations_only,
        team_conversation_ids,
    ) = _custom_role_context(workspace, user_id)
    permissions = (
        TENANT_ROLE_PERMISSIONS[membership.role]
        | WORKSPACE_ROLE_PERMISSIONS[workspace_membership.role]
        | custom_permissions
    )
    membership_agent_scope = await _agent_scope(session, workspace_membership, user_id)
    set_conversation_assignment_scope(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_membership.workspace_id,
        user_id=user_id if assigned_conversations_only else None,
        team_ids=team_conversation_ids,
    )
    return Principal(
        user_id=user_id,
        tenant_id=tenant_id,
        role=membership.role,
        token_id=payload["jti"],
        workspace_id=workspace_membership.workspace_id,
        workspace_role=workspace_membership.role,
        permissions=permissions,
        agent_ids=_merge_agent_scope(membership_agent_scope, custom_agent_scope),
        platform_actor_id=UUID(payload["platformActorId"]) if payload.get("platformActorId") else None,
        impersonation_id=str(payload["impersonationId"]) if payload.get("impersonationId") else None,
    )


CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]


def require_roles(*roles: Role) -> Callable[..., Awaitable[Principal]]:
    """Compatibility guard for workspace routes; organization roles cannot override a viewer grant."""

    async def dependency(principal: CurrentPrincipal) -> Principal:
        allowed: set[WorkspaceRole] = set()
        if Role.OWNER in roles or Role.ADMIN in roles:
            allowed.add(WorkspaceRole.ADMIN)
        if Role.MEMBER in roles:
            allowed.update({WorkspaceRole.MANAGER, WorkspaceRole.OPERATOR})
        if Role.ANALYST in roles:
            allowed.add(WorkspaceRole.ANALYST)
        if principal.workspace_id is None or principal.workspace_role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient workspace role",
            )
        return principal

    return dependency


AdminPrincipal = Annotated[Principal, Depends(require_roles(Role.OWNER, Role.ADMIN))]
WorkspaceWritePrincipal = Annotated[
    Principal,
    Depends(require_roles(Role.OWNER, Role.ADMIN, Role.MEMBER)),
]


def require_permissions(*permissions: str) -> Callable[..., Awaitable[Principal]]:
    async def dependency(principal: CurrentPrincipal) -> Principal:
        if not all(principal.can(permission) for permission in permissions):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permission",
            )
        return principal

    return dependency


def request_origin(request: Request) -> str:
    return request.headers.get("origin", "").strip().lower()
