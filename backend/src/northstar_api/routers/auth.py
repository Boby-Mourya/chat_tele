from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from northstar_api.auth_session_schemas import (
    AuthLoginOut,
    AuthMFAChallengeOut,
    AuthSessionOut,
    AuthUserOut,
)
from northstar_api.config import get_settings
from northstar_api.database import get_session
from northstar_api.dependencies import CurrentPrincipal
from northstar_api.models import Role, TenantMembership, User
from northstar_api.schemas import LoginRequest, LogoutRequest, RefreshRequest
from northstar_api.security import (
    create_access_token,
    create_mfa_challenge_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from northstar_api.services.email_verification import (
    email_is_verified,
    issue_verification_token,
    send_verification_email,
)
from northstar_api.services.password_reset import credential_version
from northstar_api.services.rate_limit import SessionStoreUnavailable, redis_services
from northstar_api.services.signup import SignupConflict, provision_signup
from northstar_api.signup_schemas import SignupRequest

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["authentication"])
DB = Annotated[AsyncSession, Depends(get_session)]
_password_verification_slots = asyncio.Semaphore(get_settings().login_hash_concurrency)
_REFRESH_COOKIE = "northstar_refresh"
_SIGNUP_WINDOW_SECONDS = 3600
_SIGNUP_SOURCE_LIMIT = 30
_SIGNUP_IDENTIFIER_LIMIT = 6


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
    # Browser production sessions use the HttpOnly cookie. Development and test
    # retain the body value for CLI compatibility and deterministic API tests.
    return None if get_settings().is_production else token


async def _enforce_signup_rate_limit(payload: SignupRequest, request: Request) -> None:
    source = request.client.host if request.client else "unknown"
    source_identifier = hashlib.sha256(source.encode("utf-8")).hexdigest()[:32]
    email_identifier = hashlib.sha256(str(payload.email).strip().lower().encode("utf-8")).hexdigest()[:32]
    for key, limit, scope in (
        (f"signup:source:{source_identifier}", _SIGNUP_SOURCE_LIMIT, "signup_source"),
        (f"signup:identifier:{email_identifier}", _SIGNUP_IDENTIFIER_LIMIT, "signup_identifier"),
    ):
        rate_limit = await redis_services.check_rate_limit(
            key,
            limit,
            _SIGNUP_WINDOW_SECONDS,
            scope=scope,
        )
        if not rate_limit.allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many account creation attempts. Try again later.",
                headers={"Retry-After": str(rate_limit.retry_after)},
            )


@router.post("/signup", response_model=AuthSessionOut, status_code=status.HTTP_201_CREATED)
async def signup(
    payload: SignupRequest,
    request: Request,
    response: Response,
    session: DB,
) -> AuthSessionOut:
    """Create a self-service owner account or accept a workspace invitation."""

    await _enforce_signup_rate_limit(payload, request)
    settings = get_settings()
    try:
        provisioned = await provision_signup(session, payload=payload)
    except SignupConflict as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Account creation conflicted with an existing account. Try signing in instead.",
        ) from None

    access_token, expires_at = create_access_token(
        provisioned.user.id,
        provisioned.tenant.id,
        provisioned.role,
    )
    refresh_token, _ = create_refresh_token(
        provisioned.user.id,
        provisioned.tenant.id,
        provisioned.role,
    )
    refresh_claims = decode_token(refresh_token, "refresh")
    try:
        await redis_services.remember_refresh_family(
            refresh_claims["fid"],
            refresh_claims["jti"],
            settings.jwt_refresh_ttl_days * 86_400,
        )
        await session.commit()
    except SessionStoreUnavailable:
        await session.rollback()
        raise HTTPException(status_code=503, detail="Session service unavailable") from None
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Account creation conflicted with an existing account. Try signing in instead.",
        ) from None

    try:
        issued = await issue_verification_token(session, provisioned.user.id)
        await session.commit()
        await send_verification_email(provisioned.user, issued.token)
    except Exception as exc:
        await session.rollback()
        # Account creation remains successful. Resend can issue a fresh challenge,
        # and delivery failures must never roll back an already-created account.
        logger.error(
            "initial_verification_email_failed",
            user_id=str(provisioned.user.id),
            error=type(exc).__name__,
        )

    _set_refresh_cookie(response, refresh_token)
    logger.info(
        "account_signup_created",
        tenant_id=str(provisioned.tenant.id),
        user_id=str(provisioned.user.id),
        workspace_id=str(provisioned.workspace.id),
        tenant_role=provisioned.role.value,
    )
    return AuthSessionOut(
        access_token=access_token,
        refresh_token=_public_refresh_token(refresh_token),
        expires_at=expires_at,
        user=AuthUserOut(
            id=provisioned.user.id,
            name=provisioned.user.name,
            email=provisioned.user.email,
            role=provisioned.role,
            email_verified=False,
        ),
    )


@router.post("/login", response_model=AuthLoginOut)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: DB,
) -> AuthLoginOut:
    settings = get_settings()
    normalized_email = payload.email.lower().strip()
    source = request.client.host if request.client else "unknown"
    source_identifier = hashlib.sha256(source.encode("utf-8")).hexdigest()[:32]
    source_limit = await redis_services.check_rate_limit(
        f"login:source:{source_identifier}",
        settings.login_global_rate_limit_per_minute,
        scope="login_source",
    )
    if not source_limit.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many sign-in attempts. Try again later.",
            headers={"Retry-After": str(source_limit.retry_after)},
        )
    identifier = hashlib.sha256(normalized_email.encode("utf-8")).hexdigest()[:32]
    rate_limit = await redis_services.check_rate_limit(
        f"login:identifier:{identifier}",
        settings.login_rate_limit_per_minute,
        scope="login",
    )
    if not rate_limit.allowed:
        logger.warning("login_rate_limited", request_id=request.headers.get("x-request-id", ""))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many sign-in attempts. Try again later.",
            headers={"Retry-After": str(rate_limit.retry_after)},
        )
    user = await session.scalar(
        select(User)
        .options(selectinload(User.memberships).selectinload(TenantMembership.tenant))
        .where(User.email == normalized_email)
    )
    # Perform exactly one Argon2 verification for present, absent, and disabled
    # accounts so account state is not exposed through a cheap timing path.
    async with _password_verification_slots:
        password_valid = await asyncio.to_thread(
            verify_password,
            payload.password,
            user.password_hash if user else None,
        )
    if not user or not user.is_active or not password_valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    if not user.memberships:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No workspace membership")
    if payload.workspace:
        membership = next(
            (item for item in user.memberships if item.tenant.slug == payload.workspace),
            None,
        )
        if not membership:
            raise HTTPException(status_code=403, detail="Requested workspace is unavailable")
    else:
        membership = min(user.memberships, key=lambda item: (item.created_at, str(item.tenant_id)))

    verified = await email_is_verified(session, user.id)
    version = await credential_version(session, user.id)
    if user.mfa_enabled:
        challenge_token, challenge_expires_at = create_mfa_challenge_token(
            user.id,
            membership.tenant_id,
            membership.role,
            credential_version=version,
        )
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        return AuthMFAChallengeOut(
            challenge_token=challenge_token,
            expires_at=challenge_expires_at,
        )

    user.last_login_at = datetime.now(UTC)
    access_token, expires_at = create_access_token(
        user.id,
        membership.tenant_id,
        membership.role,
        credential_version=version,
    )
    refresh_token, _ = create_refresh_token(
        user.id,
        membership.tenant_id,
        membership.role,
        credential_version=version,
    )
    refresh_claims = decode_token(refresh_token, "refresh")
    try:
        await redis_services.remember_refresh_family(
            refresh_claims["fid"],
            refresh_claims["jti"],
            settings.jwt_refresh_ttl_days * 86_400,
        )
    except SessionStoreUnavailable:
        raise HTTPException(status_code=503, detail="Session service unavailable") from None
    await session.commit()
    _set_refresh_cookie(response, refresh_token)
    return AuthSessionOut(
        access_token=access_token,
        refresh_token=_public_refresh_token(refresh_token),
        expires_at=expires_at,
        user=AuthUserOut(
            id=user.id,
            name=user.name,
            email=user.email,
            role=membership.role,
            email_verified=verified,
        ),
    )


@router.post("/refresh", response_model=AuthSessionOut)
async def refresh(
    request: Request,
    response: Response,
    session: DB,
    payload: RefreshRequest | None = None,
) -> AuthSessionOut:
    refresh_token = (payload.refresh_token if payload else None) or request.cookies.get(_REFRESH_COOKIE)
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    try:
        claims = decode_token(refresh_token, "refresh")
        user_id, tenant_id = UUID(claims["sub"]), UUID(claims["tid"])
        family_id, current_token_id = str(claims["fid"]), str(claims["jti"])
    except (ValueError, KeyError):
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token") from None
    membership = await session.scalar(
        select(TenantMembership)
        .options(selectinload(TenantMembership.user))
        .where(TenantMembership.user_id == user_id, TenantMembership.tenant_id == tenant_id)
    )
    if not membership or not membership.user.is_active:
        raise HTTPException(status_code=401, detail="Account or workspace is unavailable")
    version = await credential_version(session, membership.user.id)
    if int(claims.get("cv", 0)) != version:
        raise HTTPException(status_code=401, detail="Session credentials changed; sign in again")
    verified = await email_is_verified(session, membership.user.id)
    access_token, expires_at = create_access_token(
        user_id,
        tenant_id,
        membership.role,
        credential_version=version,
    )
    rotated_refresh, _ = create_refresh_token(
        user_id,
        tenant_id,
        membership.role,
        family_id=family_id,
        credential_version=version,
    )
    rotated_claims = decode_token(rotated_refresh, "refresh")
    try:
        rotated = await redis_services.rotate_refresh_family(
            family_id,
            current_token_id,
            rotated_claims["jti"],
            get_settings().jwt_refresh_ttl_days * 86_400,
        )
    except SessionStoreUnavailable:
        raise HTTPException(status_code=503, detail="Session service unavailable") from None
    if not rotated:
        raise HTTPException(status_code=401, detail="Invalid or reused refresh token")
    _set_refresh_cookie(response, rotated_refresh)
    return AuthSessionOut(
        access_token=access_token,
        refresh_token=_public_refresh_token(rotated_refresh),
        expires_at=expires_at,
        user=AuthUserOut(
            id=membership.user.id,
            name=membership.user.name,
            email=membership.user.email,
            role=membership.role,
            email_verified=verified,
        ),
    )


@router.post("/logout", status_code=204)
async def logout(
    principal: CurrentPrincipal,
    request: Request,
    payload: LogoutRequest | None = None,
) -> Response:
    settings = get_settings()
    ttl = settings.jwt_access_ttl_minutes * 60
    try:
        await redis_services.client.set(f"northstar:revoked:{principal.token_id}", "1", ex=ttl)
    except RedisError as exc:
        logger.warning("logout_revocation_cache_unavailable", error=type(exc).__name__)
        if not settings.rate_limit_fail_open:
            raise HTTPException(status_code=503, detail="Session service unavailable") from None
    refresh_token = (payload.refresh_token if payload else None) or request.cookies.get(_REFRESH_COOKIE)
    if refresh_token:
        try:
            claims = decode_token(refresh_token, "refresh")
            if claims.get("sub") == str(principal.user_id) and claims.get("tid") == str(principal.tenant_id):
                await redis_services.revoke_refresh_family(str(claims["fid"]))
        except SessionStoreUnavailable:
            raise HTTPException(status_code=503, detail="Session service unavailable") from None
        except (ValueError, KeyError):
            pass
    response = Response(status_code=204)
    response.delete_cookie(
        _REFRESH_COOKIE,
        path=f"{settings.app_api_prefix.rstrip('/')}/auth",
        secure=settings.is_production,
        httponly=True,
        samesite="strict",
    )
    return response
