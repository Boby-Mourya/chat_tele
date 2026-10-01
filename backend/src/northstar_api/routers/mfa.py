from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from northstar_api.auth_session_schemas import AuthSessionOut, AuthUserOut
from northstar_api.config import get_settings
from northstar_api.database import get_session
from northstar_api.dependencies import CurrentPrincipal
from northstar_api.mfa_schemas import (
    MFAConfirmRequest,
    MFAProtectedActionRequest,
    MFARecoveryCodesOut,
    MFASetupOut,
    MFASetupRequest,
    MFAStatusOut,
    MFAVerifyRequest,
)
from northstar_api.models import Role, TenantMembership, User
from northstar_api.security import Principal, create_access_token, create_refresh_token, decode_token
from northstar_api.services.email_verification import email_is_verified
from northstar_api.services.mfa import (
    MFAError,
    confirm_mfa,
    consume_mfa_factor,
    disable_mfa,
    mfa_status,
    regenerate_recovery_codes,
    setup_mfa,
)
from northstar_api.services.password_reset import credential_version
from northstar_api.services.rate_limit import SessionStoreUnavailable, redis_services

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/auth/mfa", tags=["authentication", "mfa"])
DB = Annotated[AsyncSession, Depends(get_session)]
_REFRESH_COOKIE = "northstar_refresh"


def _set_no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


def _set_refresh_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    _set_no_store(response)
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


async def _issue_session(
    session: AsyncSession,
    response: Response,
    *,
    user: User,
    tenant_id: UUID,
    role: Role,
    version: int,
) -> AuthSessionOut:
    verified = await email_is_verified(session, user.id)
    access_token, expires_at = create_access_token(
        user.id,
        tenant_id,
        role,
        credential_version=version,
    )
    refresh_token, _ = create_refresh_token(
        user.id,
        tenant_id,
        role,
        credential_version=version,
    )
    refresh_claims = decode_token(refresh_token, "refresh")
    try:
        await redis_services.remember_refresh_family(
            refresh_claims["fid"],
            refresh_claims["jti"],
            get_settings().jwt_refresh_ttl_days * 86_400,
        )
    except SessionStoreUnavailable:
        raise HTTPException(status_code=503, detail="Session service unavailable") from None
    _set_refresh_cookie(response, refresh_token)
    return AuthSessionOut(
        access_token=access_token,
        refresh_token=_public_refresh_token(refresh_token),
        expires_at=expires_at,
        user=AuthUserOut(
            id=user.id,
            name=user.name,
            email=user.email,
            role=role,
            email_verified=verified,
        ),
    )


async def _issue_principal_session(
    session: AsyncSession,
    response: Response,
    principal: Principal,
    *,
    version: int,
) -> AuthSessionOut:
    user = await session.get(User, principal.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Account is unavailable")
    return await _issue_session(
        session,
        response,
        user=user,
        tenant_id=principal.tenant_id,
        role=principal.role,
        version=version,
    )


@router.get("/status", response_model=MFAStatusOut)
async def status_view(principal: CurrentPrincipal, session: DB) -> MFAStatusOut:
    setting, unused = await mfa_status(session, principal.user_id)
    return MFAStatusOut(
        configured=setting is not None,
        enabled=bool(setting and setting.enabled),
        confirmed_at=setting.confirmed_at if setting else None,
        unused_recovery_codes=unused,
    )


@router.post("/setup", response_model=MFASetupOut)
async def setup(
    payload: MFASetupRequest,
    response: Response,
    principal: CurrentPrincipal,
    session: DB,
) -> MFASetupOut:
    _set_no_store(response)
    try:
        material = await setup_mfa(session, principal.user_id, payload.current_password)
        await session.commit()
    except MFAError as exc:
        await session.rollback()
        code = 409 if "already enabled" in str(exc).lower() else 400
        raise HTTPException(status_code=code, detail=str(exc)) from None
    logger.info("mfa_setup_started", user_id=str(principal.user_id))
    return MFASetupOut(
        secret=material.secret,
        otpauth_uri=material.otpauth_uri,
        recovery_codes=material.recovery_codes,
    )


@router.post("/confirm", response_model=AuthSessionOut)
async def confirm(
    payload: MFAConfirmRequest,
    response: Response,
    principal: CurrentPrincipal,
    session: DB,
) -> AuthSessionOut:
    try:
        version = await confirm_mfa(session, principal.user_id, payload.code)
        rotated = await _issue_principal_session(session, response, principal, version=version)
        await session.commit()
    except MFAError as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except HTTPException:
        await session.rollback()
        raise
    logger.info("mfa_enabled", user_id=str(principal.user_id))
    return rotated


@router.post("/verify", response_model=AuthSessionOut)
async def verify_login(
    payload: MFAVerifyRequest,
    request: Request,
    response: Response,
    session: DB,
) -> AuthSessionOut:
    try:
        claims = decode_token(payload.challenge_token, "mfa_challenge")
        user_id = UUID(str(claims["sub"]))
        tenant_id = UUID(str(claims["tid"]))
        challenge_role = str(claims["role"])
        challenge_version = int(claims.get("cv", 0))
        challenge_id = str(claims["jti"])
    except (ValueError, KeyError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid or expired MFA challenge") from None

    limit = await redis_services.check_rate_limit(
        f"mfa:challenge:{challenge_id}",
        8,
        300,
        scope="mfa_challenge",
    )
    if not limit.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many MFA attempts. Sign in again.",
            headers={"Retry-After": str(limit.retry_after)},
        )

    membership = await session.scalar(
        select(TenantMembership)
        .options(selectinload(TenantMembership.user))
        .where(TenantMembership.user_id == user_id, TenantMembership.tenant_id == tenant_id)
    )
    if (
        membership is None
        or not membership.user.is_active
        or membership.role.value != challenge_role
        or not membership.user.mfa_enabled
        or challenge_version != await credential_version(session, user_id)
    ):
        raise HTTPException(status_code=401, detail="MFA challenge is no longer valid")

    try:
        await consume_mfa_factor(
            session,
            user_id,
            code=payload.code,
            recovery_code=payload.recovery_code,
        )
        version = await credential_version(session, user_id)
        result = await _issue_session(
            session,
            response,
            user=membership.user,
            tenant_id=tenant_id,
            role=membership.role,
            version=version,
        )
    except MFAError as exc:
        await session.rollback()
        raise HTTPException(status_code=401, detail=str(exc)) from None
    except HTTPException:
        await session.rollback()
        raise

    membership.user.last_login_at = datetime.now(UTC)
    await session.commit()
    logger.info(
        "mfa_login_verified",
        user_id=str(user_id),
        request_id=request.headers.get("x-request-id", ""),
    )
    return result


@router.post("/recovery-codes", response_model=MFARecoveryCodesOut)
async def regenerate_codes(
    payload: MFAProtectedActionRequest,
    response: Response,
    principal: CurrentPrincipal,
    session: DB,
) -> MFARecoveryCodesOut:
    _set_no_store(response)
    try:
        codes = await regenerate_recovery_codes(
            session,
            principal.user_id,
            payload.current_password,
            code=payload.code,
            recovery_code=payload.recovery_code,
        )
        await session.commit()
    except MFAError as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from None
    logger.info("mfa_recovery_codes_regenerated", user_id=str(principal.user_id))
    return MFARecoveryCodesOut(recovery_codes=codes)


@router.delete("", response_model=AuthSessionOut)
async def disable(
    payload: MFAProtectedActionRequest,
    response: Response,
    principal: CurrentPrincipal,
    session: DB,
) -> AuthSessionOut:
    try:
        version = await disable_mfa(
            session,
            principal.user_id,
            payload.current_password,
            code=payload.code,
            recovery_code=payload.recovery_code,
        )
        rotated = await _issue_principal_session(session, response, principal, version=version)
        await session.commit()
    except MFAError as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except HTTPException:
        await session.rollback()
        raise
    logger.info("mfa_disabled", user_id=str(principal.user_id))
    return rotated
