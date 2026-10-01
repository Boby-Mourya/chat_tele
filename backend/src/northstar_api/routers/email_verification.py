from __future__ import annotations

import hashlib

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from northstar_api.dependencies import DBSession
from northstar_api.email_verification_schemas import (
    EmailVerificationAccepted,
    EmailVerificationResendRequest,
    EmailVerificationResult,
    EmailVerificationVerifyRequest,
)
from northstar_api.models import User
from northstar_api.modules.workspace.domain_resolution import resolve_workspace_domain
from northstar_api.services.email_verification import (
    EmailVerificationError,
    email_is_verified,
    issue_verification_token,
    send_verification_email,
    verify_email_token,
)
from northstar_api.services.rate_limit import redis_services

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/auth/email-verification", tags=["authentication"])
_RESEND_WINDOW_SECONDS = 3600
_RESEND_SOURCE_LIMIT = 30
_RESEND_IDENTIFIER_LIMIT = 5
_VERIFY_WINDOW_SECONDS = 3600
_VERIFY_SOURCE_LIMIT = 120
_VERIFY_TOKEN_LIMIT = 10


def _hash_identifier(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


async def _enforce_resend_rate_limit(email: str, request: Request) -> None:
    source = request.client.host if request.client else "unknown"
    checks = (
        (f"email-verify:source:{_hash_identifier(source)}", _RESEND_SOURCE_LIMIT, "email_verify_source"),
        (
            f"email-verify:identifier:{_hash_identifier(email)}",
            _RESEND_IDENTIFIER_LIMIT,
            "email_verify_identifier",
        ),
    )
    for key, limit, scope in checks:
        result = await redis_services.check_rate_limit(
            key,
            limit,
            _RESEND_WINDOW_SECONDS,
            scope=scope,
        )
        if not result.allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many verification email requests. Try again later.",
                headers={"Retry-After": str(result.retry_after)},
            )


async def _enforce_verify_rate_limit(token: str, request: Request) -> None:
    source = request.client.host if request.client else "unknown"
    checks = (
        (
            f"email-verify-attempt:source:{_hash_identifier(source)}",
            _VERIFY_SOURCE_LIMIT,
            "email_verify_attempt_source",
        ),
        (
            f"email-verify-attempt:token:{_hash_identifier(token)}",
            _VERIFY_TOKEN_LIMIT,
            "email_verify_attempt_token",
        ),
    )
    for key, limit, scope in checks:
        result = await redis_services.check_rate_limit(
            key,
            limit,
            _VERIFY_WINDOW_SECONDS,
            scope=scope,
        )
        if not result.allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many verification attempts. Try again later.",
                headers={"Retry-After": str(result.retry_after)},
            )


@router.post("/resend", response_model=EmailVerificationAccepted, status_code=status.HTTP_202_ACCEPTED)
async def resend_verification_email(
    payload: EmailVerificationResendRequest,
    request: Request,
    session: DBSession,
) -> EmailVerificationAccepted:
    normalized_email = str(payload.email).strip().lower()
    await _enforce_resend_rate_limit(normalized_email, request)
    user = await session.scalar(select(User).where(User.email == normalized_email, User.is_active.is_(True)))

    # Always return the same response for unknown and already-verified addresses.
    if user is None or await email_is_verified(session, user.id):
        return EmailVerificationAccepted()

    try:
        issued = await issue_verification_token(session, user.id)
        await session.commit()
        hostname = request.url.hostname or ""
        workspace = await resolve_workspace_domain(session, hostname) if hostname else None
        await send_verification_email(user, issued.token, workspace=workspace)
    except EmailVerificationError:
        await session.rollback()
    except Exception as exc:
        # Delivery failures must not become an account-existence oracle. The
        # challenge remains stored so operators can diagnose/retry safely.
        logger.error(
            "verification_email_delivery_failed",
            user_id=str(user.id),
            error=type(exc).__name__,
        )
    return EmailVerificationAccepted()


@router.post("/verify", response_model=EmailVerificationResult)
async def verify_email(
    payload: EmailVerificationVerifyRequest,
    request: Request,
    session: DBSession,
) -> EmailVerificationResult:
    await _enforce_verify_rate_limit(payload.token, request)
    try:
        verified, already_verified = await verify_email_token(session, payload.token)
        await session.commit()
    except EmailVerificationError as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return EmailVerificationResult(verified=verified, already_verified=already_verified)
