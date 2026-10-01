from __future__ import annotations

import asyncio
import hashlib
import html
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from urllib.parse import quote
from uuid import UUID

import structlog
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.email_config import EmailSettings, get_email_settings
from northstar_api.email_verification import EmailVerificationState
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
from northstar_api.modules.workspace.security_policy import email_domain_allowed, required_password_length
from northstar_api.security import hash_password
from northstar_api.services.email_verification import _smtp_send
from northstar_api.services.workspace_members import (
    replace_member_agent_access,
    validate_agent_scope,
)
from northstar_api.workspace_invitations import (
    WorkspaceInvitation,
    WorkspaceInvitationAgentAccess,
    WorkspaceInvitationStatus,
)

logger = structlog.get_logger(__name__)


class WorkspaceInvitationError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class IssuedWorkspaceInvitation:
    invitation: WorkspaceInvitation
    token: str


@dataclass(frozen=True, slots=True)
class WorkspaceInvitationDetails:
    invitation: WorkspaceInvitation
    tenant: Tenant
    workspace: Workspace
    agent_ids: tuple[UUID, ...]
    existing_user: bool


@dataclass(frozen=True, slots=True)
class AcceptedWorkspaceInvitation:
    invitation: WorkspaceInvitation
    user: User
    tenant: Tenant
    workspace: Workspace
    tenant_role: Role


def normalize_invitation_email(value: str) -> str:
    return value.strip().lower()


def workspace_invitation_token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _check_pending(invitation: WorkspaceInvitation) -> None:
    now = datetime.now(UTC)
    if invitation.status == WorkspaceInvitationStatus.PENDING and _aware(invitation.expires_at) <= now:
        invitation.status = WorkspaceInvitationStatus.EXPIRED
    messages = {
        WorkspaceInvitationStatus.EXPIRED: ("This workspace invitation has expired", 410),
        WorkspaceInvitationStatus.ACCEPTED: (
            "This workspace invitation has already been accepted",
            409,
        ),
        WorkspaceInvitationStatus.DECLINED: ("This workspace invitation was declined", 410),
        WorkspaceInvitationStatus.REVOKED: ("This workspace invitation was revoked", 410),
    }
    message = messages.get(invitation.status)
    if message:
        raise WorkspaceInvitationError(message[0], status_code=message[1])


async def _replace_invitation_access(
    session: AsyncSession,
    invitation_id: UUID,
    agent_ids: tuple[UUID, ...],
) -> None:
    await session.execute(
        delete(WorkspaceInvitationAgentAccess).where(
            WorkspaceInvitationAgentAccess.invitation_id == invitation_id
        )
    )
    session.add_all(
        [
            WorkspaceInvitationAgentAccess(invitation_id=invitation_id, agent_id=agent_id)
            for agent_id in agent_ids
        ]
    )


async def issue_workspace_invitation(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    invited_by_user_id: UUID,
    email: str,
    role: WorkspaceRole,
    all_agents_access: bool,
    agent_ids: list[UUID],
    settings: EmailSettings | None = None,
) -> IssuedWorkspaceInvitation:
    config = settings or get_email_settings()
    normalized = normalize_invitation_email(email)
    workspace = await session.scalar(
        select(Workspace)
        .where(
            Workspace.id == workspace_id,
            Workspace.tenant_id == tenant_id,
            Workspace.status == WorkspaceStatus.ACTIVE,
        )
        .with_for_update()
    )
    if workspace is None:
        raise WorkspaceInvitationError("Workspace not found", status_code=404)
    if not email_domain_allowed(workspace, normalized):
        raise WorkspaceInvitationError(
            "This email domain is not allowed by the workspace security policy",
            status_code=403,
        )
    member = await session.scalar(
        select(WorkspaceMembership.user_id)
        .join(User, User.id == WorkspaceMembership.user_id)
        .where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.tenant_id == tenant_id,
            func.lower(User.email) == normalized,
        )
    )
    if member is not None:
        raise WorkspaceInvitationError(
            "This email address is already a member of the workspace",
            status_code=409,
        )
    try:
        selected = await validate_agent_scope(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            all_agents_access=all_agents_access,
            agent_ids=agent_ids,
        )
    except RuntimeError as exc:
        raise WorkspaceInvitationError(
            str(exc),
            status_code=getattr(exc, "status_code", 400),
        ) from exc
    invitation = await session.scalar(
        select(WorkspaceInvitation)
        .where(
            WorkspaceInvitation.workspace_id == workspace_id,
            WorkspaceInvitation.email == normalized,
        )
        .with_for_update()
    )
    token = secrets.token_urlsafe(48)
    now = datetime.now(UTC)
    values = {
        "role": role,
        "all_agents_access": all_agents_access,
        "token_hash": workspace_invitation_token_hash(token),
        "status": WorkspaceInvitationStatus.PENDING,
        "invited_by_user_id": invited_by_user_id,
        "accepted_by_user_id": None,
        "expires_at": now + timedelta(days=config.workspace_invitation_ttl_days),
        "accepted_at": None,
        "terms_accepted_at": None,
        "privacy_accepted_at": None,
        "declined_at": None,
        "revoked_at": None,
        "last_delivery_error": None,
        "updated_at": now,
    }
    if invitation is None:
        invitation = WorkspaceInvitation(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            email=normalized,
            **values,
        )
        session.add(invitation)
        await session.flush()
    else:
        for field, value in values.items():
            setattr(invitation, field, value)
    await _replace_invitation_access(session, invitation.id, selected)
    await session.flush()
    return IssuedWorkspaceInvitation(invitation=invitation, token=token)


async def resend_workspace_invitation(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    invitation_id: UUID,
    invited_by_user_id: UUID,
    settings: EmailSettings | None = None,
) -> IssuedWorkspaceInvitation:
    config = settings or get_email_settings()
    invitation = await session.scalar(
        select(WorkspaceInvitation)
        .where(
            WorkspaceInvitation.id == invitation_id,
            WorkspaceInvitation.tenant_id == tenant_id,
            WorkspaceInvitation.workspace_id == workspace_id,
        )
        .with_for_update()
    )
    if invitation is None:
        raise WorkspaceInvitationError("Workspace invitation not found", status_code=404)
    if invitation.status not in {
        WorkspaceInvitationStatus.PENDING,
        WorkspaceInvitationStatus.EXPIRED,
    }:
        raise WorkspaceInvitationError(
            "Only pending or expired invitations can be resent",
            status_code=409,
        )
    token = secrets.token_urlsafe(48)
    now = datetime.now(UTC)
    invitation.token_hash = workspace_invitation_token_hash(token)
    invitation.status = WorkspaceInvitationStatus.PENDING
    invitation.invited_by_user_id = invited_by_user_id
    invitation.expires_at = now + timedelta(days=config.workspace_invitation_ttl_days)
    invitation.last_delivery_error = None
    invitation.updated_at = now
    await session.flush()
    return IssuedWorkspaceInvitation(invitation=invitation, token=token)


async def mark_workspace_invitation_delivery(
    session: AsyncSession,
    invitation: WorkspaceInvitation,
    *,
    delivered: bool,
    error: Exception | None = None,
) -> None:
    invitation.delivery_attempts += 1
    invitation.last_delivery_error = None if delivered else type(error).__name__[:500]
    if delivered:
        invitation.last_sent_at = datetime.now(UTC)
    await session.flush()


async def list_workspace_invitations(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
) -> list[WorkspaceInvitation]:
    invitations = list(
        await session.scalars(
            select(WorkspaceInvitation)
            .where(
                WorkspaceInvitation.tenant_id == tenant_id,
                WorkspaceInvitation.workspace_id == workspace_id,
                WorkspaceInvitation.status != WorkspaceInvitationStatus.ACCEPTED,
            )
            .order_by(WorkspaceInvitation.created_at.desc())
        )
    )
    now = datetime.now(UTC)
    for invitation in invitations:
        if invitation.status == WorkspaceInvitationStatus.PENDING and _aware(invitation.expires_at) <= now:
            invitation.status = WorkspaceInvitationStatus.EXPIRED
    await session.flush()
    return invitations


async def list_invitation_agent_ids(
    session: AsyncSession,
    invitation_ids: list[UUID],
) -> dict[UUID, list[UUID]]:
    result = {invitation_id: [] for invitation_id in invitation_ids}
    if not invitation_ids:
        return result
    rows = (
        await session.execute(
            select(
                WorkspaceInvitationAgentAccess.invitation_id,
                WorkspaceInvitationAgentAccess.agent_id,
            )
            .where(WorkspaceInvitationAgentAccess.invitation_id.in_(invitation_ids))
            .order_by(
                WorkspaceInvitationAgentAccess.invitation_id,
                WorkspaceInvitationAgentAccess.agent_id,
            )
        )
    ).all()
    for invitation_id, agent_id in rows:
        result.setdefault(invitation_id, []).append(agent_id)
    return result


async def revoke_workspace_invitation(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    invitation_id: UUID,
) -> None:
    invitation = await session.scalar(
        select(WorkspaceInvitation)
        .where(
            WorkspaceInvitation.id == invitation_id,
            WorkspaceInvitation.tenant_id == tenant_id,
            WorkspaceInvitation.workspace_id == workspace_id,
        )
        .with_for_update()
    )
    if invitation is None:
        raise WorkspaceInvitationError("Workspace invitation not found", status_code=404)
    if invitation.status == WorkspaceInvitationStatus.ACCEPTED:
        raise WorkspaceInvitationError(
            "Accepted invitations cannot be revoked; remove the member instead",
            status_code=409,
        )
    now = datetime.now(UTC)
    invitation.status = WorkspaceInvitationStatus.REVOKED
    invitation.revoked_at = now
    invitation.token_hash = workspace_invitation_token_hash(secrets.token_urlsafe(48))
    invitation.updated_at = now
    await session.flush()


async def preview_workspace_invitation(
    session: AsyncSession,
    raw_token: str,
    *,
    lock: bool = False,
) -> WorkspaceInvitationDetails:
    statement = (
        select(WorkspaceInvitation, Tenant, Workspace)
        .join(Tenant, Tenant.id == WorkspaceInvitation.tenant_id)
        .join(Workspace, Workspace.id == WorkspaceInvitation.workspace_id)
        .where(
            WorkspaceInvitation.token_hash == workspace_invitation_token_hash(raw_token),
            Workspace.status == WorkspaceStatus.ACTIVE,
        )
    )
    if lock:
        statement = statement.with_for_update()
    row = (await session.execute(statement)).first()
    if row is None:
        raise WorkspaceInvitationError(
            "Workspace invitation is invalid or no longer available",
            status_code=404,
        )
    invitation, tenant, workspace = row
    _check_pending(invitation)
    agent_ids = tuple(
        await session.scalars(
            select(WorkspaceInvitationAgentAccess.agent_id)
            .where(WorkspaceInvitationAgentAccess.invitation_id == invitation.id)
            .order_by(WorkspaceInvitationAgentAccess.agent_id)
        )
    )
    existing_user = (
        await session.scalar(select(User.id).where(func.lower(User.email) == invitation.email))
        is not None
    )
    return WorkspaceInvitationDetails(
        invitation=invitation,
        tenant=tenant,
        workspace=workspace,
        agent_ids=agent_ids,
        existing_user=existing_user,
    )


async def _accept_invitation(
    session: AsyncSession,
    *,
    details: WorkspaceInvitationDetails,
    user: User,
    record_consents: bool = False,
) -> AcceptedWorkspaceInvitation:
    invitation = details.invitation
    now = datetime.now(UTC)
    tenant_membership = await session.scalar(
        select(TenantMembership)
        .where(
            TenantMembership.tenant_id == invitation.tenant_id,
            TenantMembership.user_id == user.id,
        )
        .with_for_update()
    )
    if tenant_membership is None:
        tenant_membership = TenantMembership(
            tenant_id=invitation.tenant_id,
            user_id=user.id,
            role=Role.MEMBER,
        )
        session.add(tenant_membership)
    workspace_membership = await session.scalar(
        select(WorkspaceMembership)
        .where(
            WorkspaceMembership.workspace_id == invitation.workspace_id,
            WorkspaceMembership.user_id == user.id,
        )
        .with_for_update()
    )
    if workspace_membership is None:
        workspace_membership = WorkspaceMembership(
            tenant_id=invitation.tenant_id,
            workspace_id=invitation.workspace_id,
            user_id=user.id,
            role=invitation.role,
            all_agents_access=invitation.all_agents_access,
        )
        session.add(workspace_membership)
    else:
        workspace_membership.role = invitation.role
        workspace_membership.all_agents_access = invitation.all_agents_access
        workspace_membership.updated_at = now
    await replace_member_agent_access(
        session,
        workspace_id=invitation.workspace_id,
        user_id=user.id,
        agent_ids=details.agent_ids if not invitation.all_agents_access else (),
    )
    invitation.status = WorkspaceInvitationStatus.ACCEPTED
    invitation.accepted_by_user_id = user.id
    invitation.accepted_at = now
    if record_consents:
        invitation.terms_accepted_at = now
        invitation.privacy_accepted_at = now
    invitation.token_hash = workspace_invitation_token_hash(secrets.token_urlsafe(48))
    invitation.last_delivery_error = None
    invitation.updated_at = now
    user.last_login_at = now
    await session.flush()
    return AcceptedWorkspaceInvitation(
        invitation=invitation,
        user=user,
        tenant=details.tenant,
        workspace=details.workspace,
        tenant_role=tenant_membership.role,
    )


async def accept_workspace_invitation(
    session: AsyncSession,
    *,
    raw_token: str,
    user_id: UUID,
) -> AcceptedWorkspaceInvitation:
    details = await preview_workspace_invitation(session, raw_token, lock=True)
    user = await session.scalar(
        select(User).where(User.id == user_id, User.is_active.is_(True)).with_for_update()
    )
    if user is None:
        raise WorkspaceInvitationError("Account is unavailable", status_code=401)
    if normalize_invitation_email(user.email) != details.invitation.email:
        raise WorkspaceInvitationError(
            "Sign in with the email address that received this invitation",
            status_code=403,
        )
    return await _accept_invitation(session, details=details, user=user)


async def signup_with_workspace_invitation(
    session: AsyncSession,
    *,
    raw_token: str,
    name: str,
    password: str,
) -> AcceptedWorkspaceInvitation:
    details = await preview_workspace_invitation(session, raw_token, lock=True)
    minimum_length = required_password_length(details.workspace)
    if len(password) < minimum_length:
        raise WorkspaceInvitationError(
            f"Password must be at least {minimum_length} characters for this workspace",
            status_code=422,
        )
    existing = await session.scalar(
        select(User.id).where(func.lower(User.email) == details.invitation.email)
    )
    if existing is not None:
        raise WorkspaceInvitationError(
            "An account already exists for this email. Sign in to accept the invitation.",
            status_code=409,
        )
    user = User(
        email=details.invitation.email,
        name=" ".join(name.split()),
        password_hash=await asyncio.to_thread(hash_password, password),
        is_active=True,
        last_login_at=datetime.now(UTC),
    )
    session.add(user)
    await session.flush()
    session.add(EmailVerificationState(user_id=user.id, verified_at=datetime.now(UTC)))
    return await _accept_invitation(
        session,
        details=details,
        user=user,
        record_consents=True,
    )


async def decline_workspace_invitation(session: AsyncSession, raw_token: str) -> None:
    details = await preview_workspace_invitation(session, raw_token, lock=True)
    now = datetime.now(UTC)
    details.invitation.status = WorkspaceInvitationStatus.DECLINED
    details.invitation.declined_at = now
    details.invitation.token_hash = workspace_invitation_token_hash(secrets.token_urlsafe(48))
    details.invitation.updated_at = now
    await session.flush()


def workspace_invitation_url(raw_token: str, settings: EmailSettings | None = None) -> str:
    config = settings or get_email_settings()
    base = config.workspace_invitation_frontend_url.split("#", 1)[0]
    return f"{base}#token={quote(raw_token, safe='')}"


async def send_workspace_invitation_email(
    *,
    recipient_email: str,
    workspace_name: str,
    tenant_name: str,
    role: WorkspaceRole,
    raw_token: str,
    workspace: Workspace | None = None,
    settings: EmailSettings | None = None,
) -> None:
    from northstar_api.modules.workspace.email_branding import deliver_workspace_email, render_workspace_email

    config = settings or get_email_settings()
    url = workspace_invitation_url(raw_token, config)
    if workspace is not None:
        rendered = render_workspace_email(
            workspace,
            "invitation",
            context={
                "tenant_name": tenant_name,
                "workspace_name": workspace_name,
                "role": role.value,
                "recipient_email": recipient_email,
            },
            action_url=url,
            fallback_subject=f"You have been invited to {workspace_name}",
            fallback_heading=f"Join {workspace_name}",
            fallback_body=(
                f"You have been invited to join {workspace_name} in {tenant_name} as {role.value}. "
                f"This invitation expires in {config.workspace_invitation_ttl_days} days."
            ),
            fallback_button_label="Review workspace invitation",
        )
        await deliver_workspace_email(recipient_email, rendered, settings=config)
        return
    if config.email_delivery_mode == "log":
        from northstar_api.config import get_settings

        if get_settings().is_production:
            raise WorkspaceInvitationError("Email delivery is not configured", status_code=503)
        logger.info(
            "workspace_invitation_email_development",
            email=recipient_email,
            workspace=workspace_name,
            invitation_url=url,
        )
        return
    message = EmailMessage()
    message["Subject"] = f"You have been invited to {workspace_name}"
    message["From"] = f"{config.email_from_name} <{config.email_from_address}>"
    message["To"] = recipient_email
    message.set_content(
        f"You have been invited to join {workspace_name} in {tenant_name} as {role.value}.\n\n"
        f"{url}\n\n"
        f"This invitation expires in {config.workspace_invitation_ttl_days} days. "
        "If you were not expecting this invitation, you can ignore this email.\n"
    )
    safe_workspace = html.escape(workspace_name)
    safe_tenant = html.escape(tenant_name)
    safe_role = html.escape(role.value)
    safe_url = html.escape(url, quote=True)
    message.add_alternative(
        f"<p>You have been invited to join <strong>{safe_workspace}</strong> "
        f"in {safe_tenant} as <strong>{safe_role}</strong>.</p>"
        f'<p><a href="{safe_url}">Review workspace invitation</a></p>'
        f"<p>This invitation expires in {config.workspace_invitation_ttl_days} days. "
        "If you were not expecting this invitation, you can ignore this email.</p>",
        subtype="html",
    )
    await asyncio.to_thread(_smtp_send, message, config)
