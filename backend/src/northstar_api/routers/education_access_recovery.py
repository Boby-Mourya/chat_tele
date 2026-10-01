from __future__ import annotations

import hashlib
import uuid

import structlog
from fastapi import APIRouter, HTTPException, Request, status

from northstar_api.dependencies import DBSession
from northstar_api.education_access_recovery_schemas import (
    EducationAccessRecoveryAccepted,
    EducationAccessRecoveryResult,
    EducationAccessRecoveryStart,
    EducationAccessRecoveryVerify,
)
from northstar_api.services.education_access_recovery import (
    RECOVERY_TTL_SECONDS,
    EducationAccessRecoveryError,
    issue_education_access_recovery,
    send_education_recovery_email,
    verify_education_access_recovery,
)
from northstar_api.services.rate_limit import redis_services

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/education/access-recovery", tags=["education"])
_START_WINDOW_SECONDS = 3600
_START_SOURCE_LIMIT = 30
_START_PROOF_LIMIT = 5
_VERIFY_WINDOW_SECONDS = 3600
_VERIFY_SOURCE_LIMIT = 120
_VERIFY_REQUEST_LIMIT = 8


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def _source(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def _limit(key: str, limit: int, window: int, scope: str) -> None:
    result = await redis_services.check_rate_limit(key, limit, window, scope=scope)
    if not result.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many education access recovery requests. Try again later.",
            headers={"Retry-After": str(result.retry_after)},
        )


async def _enforce_start_rate_limit(payload: EducationAccessRecoveryStart, request: Request) -> None:
    proof = "|".join(
        [
            payload.agent_public_id,
            payload.student_number,
            str(payload.email),
            payload.identity_type.value,
            payload.identifier,
        ]
    )
    await _limit(
        f"education-recovery:start:source:{_hash(_source(request))}",
        _START_SOURCE_LIMIT,
        _START_WINDOW_SECONDS,
        "education_recovery_start_source",
    )
    await _limit(
        f"education-recovery:start:proof:{_hash(proof)}",
        _START_PROOF_LIMIT,
        _START_WINDOW_SECONDS,
        "education_recovery_start_proof",
    )


async def _enforce_verify_rate_limit(payload: EducationAccessRecoveryVerify, request: Request) -> None:
    await _limit(
        f"education-recovery:verify:source:{_hash(_source(request))}",
        _VERIFY_SOURCE_LIMIT,
        _VERIFY_WINDOW_SECONDS,
        "education_recovery_verify_source",
    )
    await _limit(
        f"education-recovery:verify:request:{payload.request_id}",
        _VERIFY_REQUEST_LIMIT,
        _VERIFY_WINDOW_SECONDS,
        "education_recovery_verify_request",
    )


@router.post("/start", response_model=EducationAccessRecoveryAccepted, status_code=202)
async def start_education_access_recovery(
    payload: EducationAccessRecoveryStart,
    request: Request,
    session: DBSession,
) -> EducationAccessRecoveryAccepted:
    """Start identity recovery without becoming a student/enrollment existence oracle."""

    await _enforce_start_rate_limit(payload, request)
    request_id = uuid.uuid4()
    issued = await issue_education_access_recovery(
        session,
        request_id=request_id,
        agent_public_id=payload.agent_public_id,
        student_number=payload.student_number,
        email=str(payload.email),
        identity_type=payload.identity_type,
        identifier=payload.identifier,
    )
    if issued is not None:
        await session.commit()
        try:
            await send_education_recovery_email(issued.email, issued.code)
        except Exception as exc:
            # Delivery errors must not reveal whether the supplied student proof matched.
            logger.error(
                "education_access_recovery_delivery_failed",
                request_id=str(request_id),
                error=type(exc).__name__,
            )
    else:
        # Keep the external response exactly the same for unknown student IDs,
        # wrong emails, invalid identities, inactive enrollments and wrong Agents.
        await session.rollback()

    return EducationAccessRecoveryAccepted(
        request_id=request_id,
        expires_in_seconds=RECOVERY_TTL_SECONDS,
    )


@router.post("/verify", response_model=EducationAccessRecoveryResult)
async def verify_education_access_recovery_code(
    payload: EducationAccessRecoveryVerify,
    request: Request,
    session: DBSession,
) -> EducationAccessRecoveryResult:
    await _enforce_verify_rate_limit(payload, request)
    try:
        result = await verify_education_access_recovery(
            session,
            request_id=payload.request_id,
            code=payload.code,
        )
    except EducationAccessRecoveryError as exc:
        # Commit failed-attempt counters and terminal consumption before returning
        # the same generic error for bad, expired or no-longer-authorized requests.
        await session.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from None
    await session.commit()
    return EducationAccessRecoveryResult(
        verified=result.verified,
        already_verified=result.already_verified,
    )
