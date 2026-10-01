from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import Field
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.auth_session_schemas import AuthSessionOut, AuthUserOut
from northstar_api.config import get_settings
from northstar_api.database import get_session, set_tenant_context
from northstar_api.lead_crm.audit import record_audit_event
from northstar_api.models import Role, Tenant, TenantMembership, User
from northstar_api.routers.auth import _public_refresh_token, _set_refresh_cookie
from northstar_api.schemas import APIModel
from northstar_api.security import create_access_token, create_refresh_token, decode_token
from northstar_api.services.email_verification import email_is_verified
from northstar_api.services.organization_session_transfer import (
    SessionIdentity, access_identity, refresh_identity, revoke_undelivered_family, transfer_family,
)
from northstar_api.services.outbox import enqueue_event
from northstar_api.services.password_reset import credential_version
from northstar_api.services.rate_limit import redis_services

router = APIRouter(tags=["organization sessions"])
bearer = HTTPBearer(auto_error=False)
DB = Annotated[AsyncSession, Depends(get_session)]
logger = structlog.get_logger(__name__)


class OrganizationSummary(APIModel):
    id: UUID
    name: str
    role: Role
    selected: bool


class OrganizationList(APIModel):
    organizations: list[OrganizationSummary]
    next_cursor: UUID | None = None


class OrganizationSelection(APIModel):
    organization_id: UUID
    # Non-production CLI compatibility; never retained in browser storage.
    refresh_token: str | None = Field(default=None, min_length=32, max_length=8192)


class SelectedOrganizationSession(AuthSessionOut):
    organization_id: UUID
    organization_name: str


@dataclass(frozen=True, slots=True)
class InteractiveIdentity:
    user: User
    claims: SessionIdentity


def deny(code: int, message: str) -> HTTPException:
    return HTTPException(status_code=code, detail=message, headers={"Cache-Control": "no-store"})


async def interactive_identity(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)], session: DB,
) -> InteractiveIdentity:
    if credentials is None or credentials.scheme.lower() != "bearer" or credentials.credentials.startswith("nsk_live_"):
        raise deny(401, "An interactive account session is required")
    try:
        claims = access_identity(decode_token(credentials.credentials, "access"))
    except (ValueError, KeyError, TypeError):
        raise deny(401, "Invalid or expired access token; sign in again") from None
    try:
        if await redis_services.client.exists(f"northstar:revoked:{claims.token_id}"):
            raise deny(401, "Access token was revoked")
    except RedisError:
        # Organization switching has no in-memory authentication fallback.
        raise deny(503, "Session service unavailable") from None
    user = await session.scalar(select(User).where(User.id == claims.user_id, User.is_active.is_(True)))
    if user is None or claims.credential_version != await credential_version(session, claims.user_id):
        raise deny(401, "Account credentials changed; sign in again")
    if not await email_is_verified(session, claims.user_id):
        raise deny(403, "Email verification required")
    # Do not require membership of the *old* org: a removed member may recover
    # into another still-authorized org. Target memberships are checked below.
    return InteractiveIdentity(user=user, claims=claims)


Identity = Annotated[InteractiveIdentity, Depends(interactive_identity)]


@router.get("/me/organizations", response_model=OrganizationList)
async def list_organizations(current: Identity, session: DB, response: Response,
                             after: UUID | None = None) -> OrganizationList:
    query = select(Tenant, TenantMembership).join(TenantMembership, TenantMembership.tenant_id == Tenant.id).where(
        TenantMembership.user_id == current.user.id,
    )
    if after is not None:
        query = query.where(Tenant.id > after)
    rows = (await session.execute(query.order_by(Tenant.id).limit(101))).all()
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    return OrganizationList(
        organizations=[OrganizationSummary(id=tenant.id, name=tenant.name, role=member.role,
                                           selected=tenant.id == current.claims.organization_id)
                       for tenant, member in rows[:100]],
        next_cursor=rows[99][0].id if len(rows) > 100 else None,
    )


@router.post("/auth/select-organization", response_model=SelectedOrganizationSession)
async def select_organization(payload: OrganizationSelection, current: Identity, session: DB,
                              request: Request, response: Response) -> SelectedOrganizationSession:
    settings = get_settings()
    if settings.is_production and payload.refresh_token is not None:
        raise deny(422, "Production browser sessions use the secure refresh cookie")
    raw_refresh = request.cookies.get("northstar_refresh") or payload.refresh_token
    if not raw_refresh:
        raise deny(401, "Refresh proof is required; sign in again")
    try:
        old_family, old_token = refresh_identity(decode_token(raw_refresh, "refresh"), current.claims)
    except (ValueError, KeyError, TypeError):
        raise deny(401, "Refresh proof does not match this session; sign in again") from None
    rate = await redis_services.check_rate_limit(
        f"organization-select:{current.user.id}", 30, scope="organization_select",
    )
    if not rate.allowed:
        raise HTTPException(status_code=429, detail="Too many organization changes; try again later",
                            headers={"Retry-After": str(rate.retry_after), "Cache-Control": "no-store"})
    user = await session.scalar(select(User).where(User.id == current.user.id, User.is_active.is_(True))
                                .with_for_update().execution_options(populate_existing=True))
    if user is None or await credential_version(session, current.user.id) != current.claims.credential_version:
        raise deny(401, "Account credentials changed; sign in again")
    member = await session.scalar(select(TenantMembership).where(
        TenantMembership.user_id == user.id, TenantMembership.tenant_id == payload.organization_id,
    ).with_for_update().execution_options(populate_existing=True))
    if member is None:
        raise deny(403, "Organization access is unavailable")
    tenant = await session.scalar(select(Tenant).where(Tenant.id == member.tenant_id))
    if tenant is None:
        raise deny(403, "Organization access is unavailable")
    if not await email_is_verified(session, user.id):
        raise deny(403, "Email verification required")
    version = current.claims.credential_version
    access, expires_at = create_access_token(user.id, tenant.id, member.role, credential_version=version)
    refresh, _ = create_refresh_token(user.id, tenant.id, member.role, credential_version=version)
    next_claims = decode_token(refresh, "refresh")
    new_family, new_token = str(next_claims["fid"]), str(next_claims["jti"])
    # Build the response while loaded rows are valid, before committing the session.
    result = SelectedOrganizationSession(
        access_token=access, refresh_token=_public_refresh_token(refresh), expires_at=expires_at,
        organization_id=tenant.id, organization_name=tenant.name,
        user=AuthUserOut(id=user.id, name=user.name, email=user.email, role=member.role, email_verified=True),
    )
    try:
        await set_tenant_context(session, tenant.id)
        record_audit_event(session, tenant_id=tenant.id, workspace_id=None, actor_user_id=user.id,
                           action="organization.session.selected", entity_type="organization",
                           entity_id=str(tenant.id), category="security")
        enqueue_event(session, tenant_id=tenant.id, aggregate_type="organization", aggregate_id=tenant.id,
                      event_type="organization.session.selected.v1", payload={"actorId": str(user.id)})
        await session.flush()
        if await redis_services.client.exists(f"northstar:revoked:{current.claims.token_id}"):
            raise deny(401, "Access token was revoked")
        transferred = await transfer_family(
            redis_services.client, old_family=old_family, old_token=old_token,
            new_family=new_family, new_token=new_token, ttl_seconds=settings.jwt_refresh_ttl_days * 86_400,
            access_token_id=current.claims.token_id,
        )
        if not transferred:
            raise deny(401, "The session changed in another request; sign in again")
        await session.commit()
    except Exception as exc:
        await session.rollback()
        # Redis and PostgreSQL cannot share a transaction. Compensate by revoking
        # the undelivered new family; never return tokens after an audit failure.
        try:
            await revoke_undelivered_family(redis_services.client, new_family, new_token)
        except RedisError:
            logger.warning("organization_session_compensation_failed")
        if isinstance(exc, HTTPException):
            raise
        logger.error("organization_session_selection_failed", error=type(exc).__name__)
        raise deny(503, "Organization selection could not complete; sign in again") from None
    _set_refresh_cookie(response, refresh)
    return result
