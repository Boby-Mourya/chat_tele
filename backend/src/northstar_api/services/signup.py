from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import set_tenant_context
from northstar_api.email_verification import EmailVerificationState
from northstar_api.lead_crm.audit import record_audit_event
from northstar_api.models import Role, Tenant, TenantMembership, User, Workspace, WorkspaceMembership, WorkspaceRole
from northstar_api.onboarding_contract import STARTER_CATALOG
from northstar_api.onboarding_models import OrganizationSetup
from northstar_api.security import hash_password
from northstar_api.services.outbox import enqueue_event
from northstar_api.services.subscriptions import create_subscription_for_tenant
from northstar_api.services.workspace_invitations import (
    WorkspaceInvitationError, preview_workspace_invitation, signup_with_workspace_invitation,
)
from northstar_api.signup_schemas import SignupRequest


class SignupConflict(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProvisionedSignup:
    user: User
    tenant: Tenant
    workspace: Workspace
    role: Role


def _base_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:70] or "workspace"


async def _available_tenant_slug(session: AsyncSession, organization_name: str) -> str:
    base = _base_slug(organization_name)
    if await session.scalar(select(Tenant.id).where(Tenant.slug == base)) is None:
        return base
    for _ in range(8):
        candidate = f"{base[:61]}-{uuid4().hex[:8]}"
        if await session.scalar(select(Tenant.id).where(Tenant.slug == candidate)) is None:
            return candidate
    raise SignupConflict("Unable to allocate an account identifier")


async def _provision_invited_signup(
    session: AsyncSession, *, payload: SignupRequest, normalized_email: str,
) -> ProvisionedSignup:
    if payload.workspace_invitation_token is None:
        raise SignupConflict("Workspace invitation is required")
    try:
        details = await preview_workspace_invitation(session, payload.workspace_invitation_token, lock=True)
        if details.invitation.email != normalized_email:
            raise SignupConflict("This workspace invitation was issued to a different email address")
        accepted = await signup_with_workspace_invitation(
            session, raw_token=payload.workspace_invitation_token, name=payload.name, password=payload.password,
        )
    except WorkspaceInvitationError as exc:
        raise SignupConflict(str(exc)) from None
    return ProvisionedSignup(user=accepted.user, tenant=accepted.tenant, workspace=accepted.workspace, role=accepted.tenant_role)


async def provision_signup(session: AsyncSession, *, payload: SignupRequest) -> ProvisionedSignup:
    normalized_email = str(payload.email).strip().lower()
    existing = await session.scalar(select(User.id).where(func.lower(User.email) == normalized_email))
    if existing is not None:
        raise SignupConflict("An account with this email already exists")
    if payload.workspace_invitation_token is not None:
        return await _provision_invited_signup(session, payload=payload, normalized_email=normalized_email)
    if payload.organization_name is None:
        raise SignupConflict("Organization name is required")
    password_hash = await asyncio.to_thread(hash_password, payload.password)
    accepted_at = datetime.now(UTC)
    tenant = Tenant(
        name=payload.organization_name, slug=await _available_tenant_slug(session, payload.organization_name),
        plan="free", settings_json={"signup": {
            "source": "self_service", "termsAccepted": True, "privacyAccepted": True,
            "acceptedAt": accepted_at.isoformat(), "onboardingVersion": 1,
        }},
    )
    user = User(email=normalized_email, name=payload.name, password_hash=password_hash, is_active=True, last_login_at=accepted_at)
    session.add_all([tenant, user])
    await session.flush()
    await set_tenant_context(session, tenant.id)
    await create_subscription_for_tenant(session, tenant=tenant, plan="free")
    session.add(EmailVerificationState(user_id=user.id, verified_at=None))
    workspace = Workspace(tenant_id=tenant.id, name=payload.organization_name, slug="default", created_by=user.id)
    session.add(workspace)
    await session.flush()
    session.add_all([
        TenantMembership(tenant_id=tenant.id, user_id=user.id, role=Role.OWNER),
        WorkspaceMembership(tenant_id=tenant.id, workspace_id=workspace.id, user_id=user.id, role=WorkspaceRole.ADMIN, all_agents_access=True),
        OrganizationSetup(
            tenant_id=tenant.id, required=True, profile_complete=False, revision=0,
            profile_json={}, draft_json={
                "displayName": tenant.name, "contactName": user.name, "contactEmail": user.email,
                "workspaceName": workspace.name, "workspaceSlug": workspace.slug,
            }, branding_choice="unseen", catalog_grants=[str(item["id"]) for item in STARTER_CATALOG],
        ),
    ])
    record_audit_event(
        session, tenant_id=tenant.id, workspace_id=workspace.id, actor_user_id=user.id,
        action="organization.provisioned", entity_type="organization", entity_id=str(tenant.id),
        category="workspace", metadata={"plan": "free", "onboardingVersion": 1},
    )
    enqueue_event(
        session, tenant_id=tenant.id, aggregate_type="organization", aggregate_id=tenant.id,
        event_type="organization.provisioned.v1", payload={"workspaceId": str(workspace.id), "ownerId": str(user.id)},
    )
    await session.flush()
    return ProvisionedSignup(user=user, tenant=tenant, workspace=workspace, role=Role.OWNER)
