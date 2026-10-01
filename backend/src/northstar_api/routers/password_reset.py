from __future__ import annotations

import hashlib

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from northstar_api.dependencies import DBSession
from northstar_api.models import User
from northstar_api.modules.workspace.domain_resolution import resolve_workspace_domain
from northstar_api.password_reset_schemas import (
    PasswordResetAccepted,
    PasswordResetConfirm,
    PasswordResetRequest,
    PasswordResetResult,
)
from northstar_api.services.password_reset import (
    PasswordResetError,
    issue_password_reset_token,
    reset_password_with_token,
    send_password_reset_email,
)
from northstar_api.services.rate_limit import redis_services

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/auth/password-reset", tags=["authentication"])
_RESET_WINDOW_SECONDS = 3600
_RESET_SOURCE_LIMIT = 30
_RESET_IDENTIFIER_LIMIT = 5
_CONFIRM_SOURCE_LIMIT = 60
_CONFIRM_TOKEN_LIMIT = 12


def _hash_identifier(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


async def _enforce_request_rate_limit(email: str, request: Request) -> None:
    source = request.client.host if request.client else "unknown"
    checks = (
        (f"password-reset:source:{_hash_identifier(source)}", _RESET_SOURCE_LIMIT, "password_reset_source"),
        (
            f"password-reset:identifier:{_hash_identifier(email)}",
            _RESET_IDENTIFIER_LIMIT,
            "password_reset_identifier",
        ),
    )
    for key, limit, scope in checks:
        result = await redis_services.check_rate_limit(
            key,
            limit,
            _RESET_WINDOW_SECONDS,
            scope=scope,
        )
        if not result.allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many password reset requests. Try again later.",
                headers={"Retry-After": str(result.retry_after)},
            )


async def _enforce_confirm_rate_limit(token: str, request: Request) -> None:
    source = request.client.host if request.client else "unknown"
    checks = (
        (
            f"password-reset-confirm:source:{_hash_identifier(source)}",
            _CONFIRM_SOURCE_LIMIT,
            "password_reset_confirm_source",
        ),
        (
            f"password-reset-confirm:token:{_hash_identifier(token)}",
            _CONFIRM_TOKEN_LIMIT,
            "password_reset_confirm_token",
        ),
    )
    for key, limit, scope in checks:
        result = await redis_services.check_rate_limit(
            key,
            limit,
            _RESET_WINDOW_SECONDS,
            scope=scope,
        )
        if not result.allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many password reset attempts. Try again later.",
                headers={"Retry-After": str(result.retry_after)},
            )


@router.post("/request", response_model=PasswordResetAccepted, status_code=status.HTTP_202_ACCEPTED)
async def request_password_reset(
    payload: PasswordResetRequest,
    request: Request,
    session: DBSession,
) -> PasswordResetAccepted:
    normalized_email = str(payload.email).strip().lower()
    await _enforce_request_rate_limit(normalized_email, request)
    user = await session.scalar(select(User).where(User.email == normalized_email, User.is_active.is_(True)))

    # Unknown and disabled accounts intentionally receive the same response.
    if user is None:
        return PasswordResetAccepted()

    try:
        issued = await issue_password_reset_token(session, user.id)
        await session.commit()
        hostname = request.url.hostname or ""
        workspace = await resolve_workspace_domain(session, hostname) if hostname else None
        await send_password_reset_email(user, issued.token, workspace=workspace)
    except Exception as exc:
        await session.rollback()
        logger.error(
            "password_reset_delivery_failed",
            user_id=str(user.id),
            error=type(exc).__name__,
        )
    return PasswordResetAccepted()


@router.post("/confirm", response_model=PasswordResetResult)
async def confirm_password_reset(
    payload: PasswordResetConfirm,
    request: Request,
    session: DBSession,
) -> PasswordResetResult:
    await _enforce_confirm_rate_limit(payload.token, request)
    try:
        await reset_password_with_token(session, payload.token, payload.password)
        await session.commit()
    except PasswordResetError as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return PasswordResetResult()
