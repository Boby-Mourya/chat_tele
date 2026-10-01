from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

from httpx import AsyncClient
from sqlalchemy import select

import northstar_api.routers.auth as auth_router_module
import northstar_api.routers.email_verification as verification_router_module
from northstar_api.database import SessionFactory
from northstar_api.email_verification import EmailVerificationState, EmailVerificationToken
from northstar_api.models import User
from northstar_api.services.rate_limit import RateLimitResult, redis_services


def signup_payload(seed: str, email: str) -> dict[str, object]:
    return {
        "name": "Verification Owner",
        "email": email,
        "password": "Verification-Password-2026!",
        "organizationName": f"Verification Organization {seed}",
        "termsAccepted": True,
        "privacyAccepted": True,
    }


async def test_email_verification_unlocks_workspace_and_refreshes_session(
    client: AsyncClient,
    monkeypatch,
) -> None:
    captured_tokens: list[str] = []

    async def capture_email(_user: User, token: str) -> None:
        captured_tokens.append(token)

    monkeypatch.setattr(auth_router_module, "send_verification_email", capture_email)
    seed = uuid.uuid4().hex[:10]
    email = f"verify-{seed}@example.com"
    signup = await client.post("/api/v1/auth/signup", json=signup_payload(seed, email))
    assert signup.status_code == 201, signup.text
    assert signup.json()["user"]["emailVerified"] is False
    assert len(captured_tokens) == 1
    raw_token = captured_tokens[0]
    assert raw_token

    access_headers = {"Authorization": f"Bearer {signup.json()['accessToken']}"}
    blocked = await client.get("/api/v1/workspaces", headers=access_headers)
    assert blocked.status_code == 403
    assert blocked.json()["error"]["message"] == "Email verification required"

    verified = await client.post(
        "/api/v1/auth/email-verification/verify",
        json={"token": raw_token},
    )
    assert verified.status_code == 200, verified.text
    assert verified.json() == {"verified": True, "alreadyVerified": False}

    repeated = await client.post(
        "/api/v1/auth/email-verification/verify",
        json={"token": raw_token},
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json() == {"verified": True, "alreadyVerified": True}

    refreshed = await client.post("/api/v1/auth/refresh")
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["user"]["emailVerified"] is True

    unlocked = await client.get("/api/v1/workspaces", headers=access_headers)
    assert unlocked.status_code == 200, unlocked.text
    assert len(unlocked.json()) == 1

    async with SessionFactory() as session:
        user = await session.scalar(select(User).where(User.email == email))
        assert user is not None
        state = await session.get(EmailVerificationState, user.id)
        assert state is not None
        assert state.verified_at is not None
        token = await session.scalar(
            select(EmailVerificationToken).where(EmailVerificationToken.user_id == user.id)
        )
        assert token is not None
        assert token.consumed_at is not None
        assert token.token_hash == hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        assert raw_token != token.token_hash


async def test_resend_invalidates_old_link_and_is_generic(
    client: AsyncClient,
    monkeypatch,
) -> None:
    captured_tokens: list[str] = []

    async def capture_email(_user: User, token: str) -> None:
        captured_tokens.append(token)

    monkeypatch.setattr(auth_router_module, "send_verification_email", capture_email)
    monkeypatch.setattr(verification_router_module, "send_verification_email", capture_email)
    seed = uuid.uuid4().hex[:10]
    email = f"resend-{seed}@example.com"
    signup = await client.post("/api/v1/auth/signup", json=signup_payload(seed, email))
    assert signup.status_code == 201, signup.text
    assert len(captured_tokens) == 1
    first_token = captured_tokens[0]

    resend = await client.post(
        "/api/v1/auth/email-verification/resend",
        json={"email": email.upper()},
    )
    assert resend.status_code == 202, resend.text
    assert resend.json() == {"accepted": True}
    assert len(captured_tokens) == 2
    second_token = captured_tokens[1]
    assert second_token != first_token

    old_link = await client.post(
        "/api/v1/auth/email-verification/verify",
        json={"token": first_token},
    )
    assert old_link.status_code == 400
    assert old_link.json()["error"]["message"] == "Verification link is invalid or expired"

    new_link = await client.post(
        "/api/v1/auth/email-verification/verify",
        json={"token": second_token},
    )
    assert new_link.status_code == 200, new_link.text

    already_verified_resend = await client.post(
        "/api/v1/auth/email-verification/resend",
        json={"email": email},
    )
    assert already_verified_resend.status_code == 202
    assert len(captured_tokens) == 2

    unknown_resend = await client.post(
        "/api/v1/auth/email-verification/resend",
        json={"email": f"unknown-{seed}@example.com"},
    )
    assert unknown_resend.status_code == 202
    assert unknown_resend.json() == {"accepted": True}
    assert len(captured_tokens) == 2


async def test_expired_verification_token_is_rejected(client: AsyncClient, monkeypatch) -> None:
    captured_tokens: list[str] = []

    async def capture_email(_user: User, token: str) -> None:
        captured_tokens.append(token)

    monkeypatch.setattr(auth_router_module, "send_verification_email", capture_email)
    seed = uuid.uuid4().hex[:10]
    email = f"expired-{seed}@example.com"
    signup = await client.post("/api/v1/auth/signup", json=signup_payload(seed, email))
    assert signup.status_code == 201, signup.text
    raw_token = captured_tokens[0]

    async with SessionFactory() as session:
        user = await session.scalar(select(User).where(User.email == email))
        assert user is not None
        token = await session.scalar(
            select(EmailVerificationToken).where(EmailVerificationToken.user_id == user.id)
        )
        assert token is not None
        token.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await session.commit()

    response = await client.post(
        "/api/v1/auth/email-verification/verify",
        json={"token": raw_token},
    )
    assert response.status_code == 400
    assert response.json()["error"]["message"] == "Verification link is invalid or expired"


async def test_unverified_account_can_logout(client: AsyncClient, monkeypatch) -> None:
    monkeypatch.setattr(auth_router_module, "send_verification_email", AsyncMock())
    seed = uuid.uuid4().hex[:10]
    email = f"logout-unverified-{seed}@example.com"
    signup = await client.post("/api/v1/auth/signup", json=signup_payload(seed, email))
    assert signup.status_code == 201, signup.text

    response = await client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {signup.json()['accessToken']}"},
    )
    assert response.status_code == 204, response.text


async def test_verification_resend_rate_limit_sets_retry_after(client: AsyncClient, monkeypatch) -> None:
    limiter = AsyncMock(
        side_effect=[RateLimitResult(True, 29, 900), RateLimitResult(False, 0, 900)]
    )
    monkeypatch.setattr(redis_services, "check_rate_limit", limiter)

    response = await client.post(
        "/api/v1/auth/email-verification/resend",
        json={"email": "rate-limit-verification@example.com"},
    )
    assert response.status_code == 429, response.text
    assert response.headers["retry-after"] == "900"
    assert response.json()["error"]["message"] == "Too many verification email requests. Try again later."
    assert limiter.await_count == 2


async def test_verification_attempt_rate_limit_sets_retry_after(client: AsyncClient, monkeypatch) -> None:
    limiter = AsyncMock(
        side_effect=[RateLimitResult(True, 119, 600), RateLimitResult(False, 0, 600)]
    )
    monkeypatch.setattr(redis_services, "check_rate_limit", limiter)

    response = await client.post(
        "/api/v1/auth/email-verification/verify",
        json={"token": "verification-rate-limit-token-value-1234567890"},
    )

    assert response.status_code == 429, response.text
    assert response.headers["retry-after"] == "600"
    assert response.json()["error"]["message"] == "Too many verification attempts. Try again later."
    assert limiter.await_count == 2


async def test_legacy_seed_user_is_verified_by_compatibility(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "Correct-Horse-Test-Password-42!"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["user"]["emailVerified"] is True
