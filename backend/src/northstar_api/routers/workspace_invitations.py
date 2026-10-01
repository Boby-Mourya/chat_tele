from __future__ import annotations

import hashlib
from typing import Annotated, Literal
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from northstar_api.auth_session_schemas import AuthUserOut
from northstar_api.config import get_settings
from northstar_api.dependencies import CurrentPrincipal, DBSession, require_permissions
from northstar_api.lead_crm.audit import record_audit_event
from northstar_api.models import Tenant, Workspace
from northstar_api.security import (
    Principal,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from northstar_api.services.outbox import enqueue_event
from northstar_api.services.password_reset import credential_version
from northstar_api.services.rate_limit import SessionStoreUnavailable, redis_services
from northstar_api.services.workspace_invitations import (
    AcceptedWorkspaceInvitation,
    WorkspaceInvitationError,
    accept_workspace_invitation,
    decline_workspace_invitation,
    issue_workspace_invitation,
    list_invitation_agent_ids,
    list_workspace_invitations,
    mark_workspace_invitation_delivery,
    preview_workspace_invitation,
    resend_workspace_invitation,
    revoke_workspace_invitation,
    send_workspace_invitation_email,
    signup_with_workspace_invitation,
)
from northstar_api.services.workspace_members import (
    WorkspaceMemberError,
    list_workspace_members,
    remove_workspace_member,
    update_workspace_member,
)
from northstar_api.workspace_invitation_schemas import (
    WorkspaceInvitationCreate,
    WorkspaceInvitationDeclined,
    WorkspaceInvitationOut,
    WorkspaceInvitationPreview,
    WorkspaceInvitationSessionOut,
    WorkspaceInvitationSignupRequest,
    WorkspaceInvitationTokenRequest,
    WorkspaceMemberOut,
    WorkspaceMemberPatch,
)
from northstar_api.workspace_invitations import WorkspaceInvitation

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/workspace", tags=["workspace members"])
public_router = APIRouter(prefix="/workspace-invitations", tags=["workspace invitations"])
MemberViewPrincipal = Annotated[Principal, Depends(require_permissions("members.view"))]
MemberManagePrincipal = Annotated[Principal, Depends(require_permissions("members.manage"))]
_INVITATION_WINDOW_SECONDS = 3600
_INVITATION_SOURCE_LIMIT = 120
_INVITATION_TOKEN_LIMIT = 20
_INVITED_SIGNUP_SOURCE_LIMIT = 20
_INVITED_SIGNUP_TOKEN_LIMIT = 6
_REFRESH_COOKIE = "northstar_refresh"


def _http_error(exc: WorkspaceInvitationError | WorkspaceMemberError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


def _identifier(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def _record_member_event(
    session: DBSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    actor_user_id: UUID,
    action: str,
    entity_type: str,
    entity_id: str,
    metadata: dict[str, object] | None = None,
) -> None:
    record_audit_event(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        category="workspace",
        metadata=metadata or {},
    )
    enqueue_event(
        session,
        tenant_id=tenant_id,
        aggregate_type=entity_type,
        aggregate_id=workspace_id,
        event_type=f"{action}.v1",
        payload={"workspaceId": str(workspace_id), "entityId": entity_id},
    )


async def _enforce_public_rate_limit(
    request: Request,
    token: str,
    *,
    source_limit: int = _INVITATION_SOURCE_LIMIT,
    token_limit: int = _INVITATION_TOKEN_LIMIT,
    scope: str = "workspace_invitation",
) -> None:
    source = request.client.host if request.client else "unknown"
    checks = (
        (f"{scope}:source:{_identifier(source)}", source_limit, f"{scope}_source"),
        (f"{scope}:token:{_identifier(token)}", token_limit, f"{scope}_token"),
    )
    for key, limit, rate_scope in checks:
        result = await redis_services.check_rate_limit(
            key,
            limit,
            _INVITATION_WINDOW_SECONDS,
            scope=rate_scope,
        )
        if not result.allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many workspace invitation attempts. Try again later.",
                headers={"Retry-After": str(result.retry_after)},
            )


def _delivery_state(
    invitation: WorkspaceInvitation,
) -> Literal["not-sent", "sent", "failed"]:
    if invitation.last_delivery_error:
        return "failed"
    if invitation.last_sent_at is not None:
        return "sent"
    return "not-sent"


def _invitation_out(
    invitation: WorkspaceInvitation,
    agent_ids: list[UUID],
) -> WorkspaceInvitationOut:
    return WorkspaceInvitationOut(
        id=invitation.id,
        email=invitation.email,
        role=invitation.role,
        all_agents_access=invitation.all_agents_access,
        agent_ids=agent_ids,
        status=invitation.status,
        expires_at=invitation.expires_at,
        last_sent_at=invitation.last_sent_at,
        delivery_attempts=invitation.delivery_attempts,
        delivery_state=_delivery_state(invitation),
        created_at=invitation.created_at,
    )


def _set_refresh_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.set_cookie(
        _REFRESH_COOKIE,
        token,
        max_age=settings.jwt_refresh_ttl_days * 86_400,
        httponly=True,
        secure=settings.is_production,
        samesite="strict",
        path=f"{settings.app_api_prefix.rstrip('/')}/auth",
    )


def _public_refresh_token(token: str) -> str | None:
    return None if get_settings().is_production else token


async def _session_response(
    session: DBSession,
    response: Response,
    accepted: AcceptedWorkspaceInvitation,
) -> WorkspaceInvitationSessionOut:
    version = await credential_version(session, accepted.user.id)
    access_token, expires_at = create_access_token(
        accepted.user.id,
        accepted.tenant.id,
        accepted.tenant_role,
        credential_version=version,
    )
    refresh_token, _ = create_refresh_token(
        accepted.user.id,
        accepted.tenant.id,
        accepted.tenant_role,
        credential_version=version,
    )
    refresh_claims = decode_token(refresh_token, "refresh")
    try:
        await redis_services.remember_refresh_family(
            refresh_claims["fid"],
            refresh_claims["jti"],
            get_settings().jwt_refresh_ttl_days * 86_400,
        )
        _record_member_event(
            session,
            tenant_id=accepted.tenant.id,
            workspace_id=accepted.workspace.id,
            actor_user_id=accepted.user.id,
            action="workspace.member.joined",
            entity_type="workspace_member",
            entity_id=str(accepted.user.id),
            metadata={"role": accepted.invitation.role.value},
        )
        await session.commit()
    except SessionStoreUnavailable:
        await session.rollback()
        raise HTTPException(status_code=503, detail="Session service unavailable") from None
    _set_refresh_cookie(response, refresh_token)
    return WorkspaceInvitationSessionOut(
        access_token=access_token,
        refresh_token=_public_refresh_token(refresh_token),
        expires_at=expires_at,
        user=AuthUserOut(
            id=accepted.user.id,
            name=accepted.user.name,
            email=accepted.user.email,
            role=accepted.tenant_role,
            email_verified=True,
        ),
        tenant_id=accepted.tenant.id,
        tenant_slug=accepted.tenant.slug,
        workspace_id=accepted.workspace.id,
    )


async def _workspace_context(
    session: DBSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
) -> tuple[str, Workspace]:
    row = (
        await session.execute(
            select(Tenant.name, Workspace)
            .join(Workspace, Workspace.tenant_id == Tenant.id)
            .where(Tenant.id == tenant_id, Workspace.id == workspace_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    tenant_name, workspace = row
    return tenant_name, workspace


async def _deliver_invitation(
    session: DBSession,
    invitation: WorkspaceInvitation,
    raw_token: str,
    *,
    tenant_name: str,
    workspace: Workspace,
) -> None:
    delivery_error: Exception | None = None
    try:
        await send_workspace_invitation_email(
            recipient_email=invitation.email,
            workspace_name=workspace.name,
            tenant_name=tenant_name,
            role=invitation.role,
            raw_token=raw_token,
            workspace=workspace,
        )
    except Exception as exc:
        delivery_error = exc
        logger.error(
            "workspace_invitation_delivery_failed",
            invitation_id=str(invitation.id),
            workspace_id=str(invitation.workspace_id),
            error=type(exc).__name__,
        )
    await mark_workspace_invitation_delivery(
        session,
        invitation,
        delivered=delivery_error is None,
        error=delivery_error,
    )
    await session.commit()


@router.get("/members", response_model=list[WorkspaceMemberOut])
async def get_workspace_members(
    principal: MemberViewPrincipal,
    session: DBSession,
) -> list[WorkspaceMemberOut]:
    assert principal.workspace_id is not None
    members = await list_workspace_members(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
    )
    return [
        WorkspaceMemberOut(
            user_id=item.user.id,
            name=item.user.name,
            email=item.user.email,
            role=item.membership.role,
            all_agents_access=item.membership.all_agents_access,
            agent_ids=list(item.agent_ids),
            joined_at=item.membership.created_at,
            is_self=item.user.id == principal.user_id,
        )
        for item in members
    ]


@router.patch("/members/{member_user_id}", response_model=WorkspaceMemberOut)
async def patch_workspace_member(
    member_user_id: UUID,
    payload: WorkspaceMemberPatch,
    principal: MemberManagePrincipal,
    session: DBSession,
) -> WorkspaceMemberOut:
    assert principal.workspace_id is not None
    try:
        member = await update_workspace_member(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            actor_user_id=principal.user_id,
            member_user_id=member_user_id,
            role=payload.role,
            all_agents_access=payload.all_agents_access,
            agent_ids=payload.agent_ids,
        )
        _record_member_event(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            actor_user_id=principal.user_id,
            action="workspace.member.updated",
            entity_type="workspace_member",
            entity_id=str(member_user_id),
            metadata={"role": payload.role.value, "allAgentsAccess": payload.all_agents_access},
        )
        await session.commit()
    except WorkspaceMemberError as exc:
        await session.rollback()
        raise _http_error(exc) from None
    return WorkspaceMemberOut(
        user_id=member.user.id,
        name=member.user.name,
        email=member.user.email,
        role=member.membership.role,
        all_agents_access=member.membership.all_agents_access,
        agent_ids=list(member.agent_ids),
        joined_at=member.membership.created_at,
        is_self=member.user.id == principal.user_id,
    )


@router.delete("/members/{member_user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace_member(
    member_user_id: UUID,
    principal: MemberManagePrincipal,
    session: DBSession,
) -> Response:
    assert principal.workspace_id is not None
    try:
        await remove_workspace_member(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            actor_user_id=principal.user_id,
            member_user_id=member_user_id,
        )
        _record_member_event(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            actor_user_id=principal.user_id,
            action="workspace.member.removed",
            entity_type="workspace_member",
            entity_id=str(member_user_id),
        )
        await session.commit()
    except WorkspaceMemberError as exc:
        await session.rollback()
        raise _http_error(exc) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/invitations", response_model=list[WorkspaceInvitationOut])
async def get_workspace_invitations(
    principal: MemberViewPrincipal,
    session: DBSession,
) -> list[WorkspaceInvitationOut]:
    assert principal.workspace_id is not None
    invitations = await list_workspace_invitations(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
    )
    agent_ids = await list_invitation_agent_ids(
        session,
        [invitation.id for invitation in invitations],
    )
    await session.commit()
    return [
        _invitation_out(invitation, agent_ids.get(invitation.id, []))
        for invitation in invitations
    ]


@router.post(
    "/invitations",
    response_model=WorkspaceInvitationOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_workspace_invitation(
    payload: WorkspaceInvitationCreate,
    principal: MemberManagePrincipal,
    session: DBSession,
) -> WorkspaceInvitationOut:
    assert principal.workspace_id is not None
    try:
        issued = await issue_workspace_invitation(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            invited_by_user_id=principal.user_id,
            email=str(payload.email),
            role=payload.role,
            all_agents_access=payload.all_agents_access,
            agent_ids=payload.agent_ids,
        )
        _record_member_event(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            actor_user_id=principal.user_id,
            action="workspace.member.invited",
            entity_type="workspace_invitation",
            entity_id=str(issued.invitation.id),
            metadata={"role": payload.role.value},
        )
        await session.commit()
    except WorkspaceInvitationError as exc:
        await session.rollback()
        raise _http_error(exc) from None
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="A workspace invitation for this email is already being updated",
        ) from None
    tenant_name, workspace = await _workspace_context(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
    )
    await _deliver_invitation(
        session,
        issued.invitation,
        issued.token,
        tenant_name=tenant_name,
        workspace=workspace,
    )
    return _invitation_out(issued.invitation, payload.agent_ids)


@router.post(
    "/invitations/{invitation_id}/resend",
    response_model=WorkspaceInvitationOut,
)
async def resend_invitation(
    invitation_id: UUID,
    principal: MemberManagePrincipal,
    session: DBSession,
) -> WorkspaceInvitationOut:
    assert principal.workspace_id is not None
    try:
        issued = await resend_workspace_invitation(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            invitation_id=invitation_id,
            invited_by_user_id=principal.user_id,
        )
        agent_ids = await list_invitation_agent_ids(session, [invitation_id])
        _record_member_event(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            actor_user_id=principal.user_id,
            action="workspace.member.invitation.resent",
            entity_type="workspace_invitation",
            entity_id=str(invitation_id),
        )
        await session.commit()
    except WorkspaceInvitationError as exc:
        await session.rollback()
        raise _http_error(exc) from None
    tenant_name, workspace = await _workspace_context(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
    )
    await _deliver_invitation(
        session,
        issued.invitation,
        issued.token,
        tenant_name=tenant_name,
        workspace=workspace,
    )
    return _invitation_out(issued.invitation, agent_ids.get(invitation_id, []))


@router.delete(
    "/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_invitation(
    invitation_id: UUID,
    principal: MemberManagePrincipal,
    session: DBSession,
) -> Response:
    assert principal.workspace_id is not None
    try:
        await revoke_workspace_invitation(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            invitation_id=invitation_id,
        )
        _record_member_event(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            actor_user_id=principal.user_id,
            action="workspace.member.invitation.revoked",
            entity_type="workspace_invitation",
            entity_id=str(invitation_id),
        )
        await session.commit()
    except WorkspaceInvitationError as exc:
        await session.rollback()
        raise _http_error(exc) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@public_router.post("/preview", response_model=WorkspaceInvitationPreview)
async def preview_invitation(
    payload: WorkspaceInvitationTokenRequest,
    request: Request,
    response: Response,
    session: DBSession,
) -> WorkspaceInvitationPreview:
    await _enforce_public_rate_limit(request, payload.token)
    try:
        details = await preview_workspace_invitation(session, payload.token)
    except WorkspaceInvitationError as exc:
        await session.rollback()
        raise _http_error(exc) from None
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return WorkspaceInvitationPreview(
        invitation_id=details.invitation.id,
        email=details.invitation.email,
        tenant_id=details.tenant.id,
        tenant_name=details.tenant.name,
        tenant_slug=details.tenant.slug,
        workspace_id=details.workspace.id,
        workspace_name=details.workspace.name,
        role=details.invitation.role,
        all_agents_access=details.invitation.all_agents_access,
        agent_count=len(details.agent_ids),
        expires_at=details.invitation.expires_at,
        existing_user=details.existing_user,
    )


@public_router.post("/decline", response_model=WorkspaceInvitationDeclined)
async def decline_invitation(
    payload: WorkspaceInvitationTokenRequest,
    request: Request,
    session: DBSession,
) -> WorkspaceInvitationDeclined:
    await _enforce_public_rate_limit(request, payload.token)
    try:
        await decline_workspace_invitation(session, payload.token)
        await session.commit()
    except WorkspaceInvitationError as exc:
        await session.rollback()
        raise _http_error(exc) from None
    return WorkspaceInvitationDeclined()


@public_router.post("/accept", response_model=WorkspaceInvitationSessionOut)
async def accept_invitation(
    payload: WorkspaceInvitationTokenRequest,
    request: Request,
    response: Response,
    principal: CurrentPrincipal,
    session: DBSession,
) -> WorkspaceInvitationSessionOut:
    await _enforce_public_rate_limit(request, payload.token)
    try:
        accepted = await accept_workspace_invitation(
            session,
            raw_token=payload.token,
            user_id=principal.user_id,
        )
        return await _session_response(session, response, accepted)
    except WorkspaceInvitationError as exc:
        await session.rollback()
        raise _http_error(exc) from None


@public_router.post(
    "/signup",
    response_model=WorkspaceInvitationSessionOut,
    status_code=status.HTTP_201_CREATED,
)
async def invited_signup(
    payload: WorkspaceInvitationSignupRequest,
    request: Request,
    response: Response,
    session: DBSession,
) -> WorkspaceInvitationSessionOut:
    await _enforce_public_rate_limit(
        request,
        payload.token,
        source_limit=_INVITED_SIGNUP_SOURCE_LIMIT,
        token_limit=_INVITED_SIGNUP_TOKEN_LIMIT,
        scope="workspace_invited_signup",
    )
    try:
        accepted = await signup_with_workspace_invitation(
            session,
            raw_token=payload.token,
            name=payload.name,
            password=payload.password,
        )
        return await _session_response(session, response, accepted)
    except WorkspaceInvitationError as exc:
        await session.rollback()
        raise _http_error(exc) from None
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="An account already exists for this email. Sign in to accept the invitation.",
        ) from None
