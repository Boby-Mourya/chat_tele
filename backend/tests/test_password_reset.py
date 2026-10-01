from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

from httpx import AsyncClient
from sqlalchemy import select

import northstar_api.routers.auth as auth_router_module
import northstar_api.routers.password_reset as reset_router_module
from northstar_api.database import SessionFactory
from northstar_api.models import User
from northstar_api.password_reset import PasswordCredentialState, PasswordResetToken
from northstar_api.services.rate_limit import RateLimitResult, redis_services


def signup_payload(seed: str, email: str, password: str) -> dict[str, object]:
    return {
        "name": "Password Reset Owner",
        "email": email,
        "password": password,
        "organizationName": f"Password Reset Organization {seed}",
        "termsAccepted": True,
        "privacyAccepted": True,
    }


async def test_password_reset_rotates_credentials_and_preserves_verification_state(
    client: AsyncClient,
    monkeypatch,
) -> None:
    reset_tokens: list[str] = []

    async def capture_reset(_user: User, token: str) -> None:
        reset_tokens.append(token)

    monkeypatch.setattr(auth_router_module, "send_verification_email", AsyncMock())
    monkeypatch.setattr(reset_router_module, "send_password_reset_email", capture_reset)

    seed = uuid.uuid4().hex[:10]
    email = f"password-reset-{seed}@example.com"
    old_password = "Original-Password-2026!"
    new_password = "Replacement-Password-2026!"
    signup = await client.post("/api/v1/auth/signup", json=signup_payload(seed, email, old_password))
    assert signup.status_code == 201, signup.text
    old_access = signup.json()["accessToken"]
    old_refresh = signup.json()["refreshToken"]
    assert signup.json()["user"]["emailVerified"] is False

    requested = await client.post("/api/v1/auth/password-reset/request", json={"email": email.upper()})
    assert requested.status_code == 202, requested.text
    assert requested.json() == {"accepted": True}
    assert len(reset_tokens) == 1
    first_token = reset_tokens[0]

    requested_again = await client.post("/api/v1/auth/password-reset/request", json={"email": email})
    assert requested_again.status_code == 202
    assert len(reset_tokens) == 2
    second_token = reset_tokens[1]
    assert first_token != second_token

    first_attempt = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": first_token, "password": new_password, "confirmPassword": new_password},
    )
    assert first_attempt.status_code == 400
    assert first_attempt.json()["error"]["message"] == "Password reset link is invalid or expired"

    same_password = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": second_token, "password": old_password, "confirmPassword": old_password},
    )
    assert same_password.status_code == 400
    assert same_password.json()["error"]["message"] == "Choose a password different from your current password"

    completed = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": second_token, "password": new_password, "confirmPassword": new_password},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json() == {"reset": True}

    replay = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": second_token, "password": "Another-Password-2026!", "confirmPassword": "Another-Password-2026!"},
    )
    assert replay.status_code == 400

    stale_access = await client.get(
        "/api/v1/workspaces",
        headers={"Authorization": f"Bearer {old_access}"},
    )
    assert stale_access.status_code == 401
    assert stale_access.json()["error"]["message"] == "Session credentials changed; sign in again"

    stale_refresh = await client.post(
        "/api/v1/auth/refresh",
        json={"refreshToken": old_refresh},
    )
    assert stale_refresh.status_code == 401
    assert stale_refresh.json()["error"]["message"] == "Session credentials changed; sign in again"

    old_login = await client.post("/api/v1/auth/login", json={"email": email, "password": old_password})
    assert old_login.status_code == 401

    new_login = await client.post("/api/v1/auth/login", json={"email": email, "password": new_password})
    assert new_login.status_code == 200, new_login.text
    assert new_login.json()["user"]["emailVerified"] is False

    async with SessionFactory() as session:
        user = await session.scalar(select(User).where(User.email == email))
        assert user is not None
        state = await session.get(PasswordCredentialState, user.id)
        assert state is not None
        assert state.version == 1
        tokens = list(
            await session.scalars(
                select(PasswordResetToken).where(PasswordResetToken.user_id == user.id)
            )
        )
        assert len(tokens) == 2
        second = next(
            item
            for item in tokens
            if item.token_hash == hashlib.sha256(second_token.encode("utf-8")).hexdigest()
        )
        assert second.consumed_at is not None
        assert second.token_hash != second_token


async def test_password_reset_request_is_generic_for_unknown_account(
    client: AsyncClient,
    monkeypatch,
) -> None:
    sender = AsyncMock()
    monkeypatch.setattr(reset_router_module, "send_password_reset_email", sender)
    response = await client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": f"unknown-{uuid.uuid4().hex}@example.com"},
    )
    assert response.status_code == 202
    assert response.json() == {"accepted": True}
    sender.assert_not_awaited()


async def test_expired_password_reset_token_is_rejected(client: AsyncClient, monkeypatch) -> None:
    captured: list[str] = []

    async def capture_reset(_user: User, token: str) -> None:
        captured.append(token)

    monkeypatch.setattr(auth_router_module, "send_verification_email", AsyncMock())
    monkeypatch.setattr(reset_router_module, "send_password_reset_email", capture_reset)
    seed = uuid.uuid4().hex[:10]
    email = f"expired-reset-{seed}@example.com"
    password = "Original-Password-2026!"
    signup = await client.post("/api/v1/auth/signup", json=signup_payload(seed, email, password))
    assert signup.status_code == 201
    requested = await client.post("/api/v1/auth/password-reset/request", json={"email": email})
    assert requested.status_code == 202
    raw_token = captured[0]

    async with SessionFactory() as session:
        token = await session.scalar(
            select(PasswordResetToken).where(
                PasswordResetToken.token_hash == hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
            )
        )
        assert token is not None
        token.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await session.commit()

    response = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={
            "token": raw_token,
            "password": "Replacement-Password-2026!",
            "confirmPassword": "Replacement-Password-2026!",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["message"] == "Password reset link is invalid or expired"


async def test_password_reset_request_rate_limit_sets_retry_after(client: AsyncClient, monkeypatch) -> None:
    limiter = AsyncMock(
        side_effect=[RateLimitResult(True, 29, 600), RateLimitResult(False, 0, 600)]
    )
    monkeypatch.setattr(redis_services, "check_rate_limit", limiter)
    response = await client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "rate-limit-reset@example.com"},
    )
    assert response.status_code == 429
    assert response.headers["retry-after"] == "600"
    assert response.json()["error"]["message"] == "Too many password reset requests. Try again later."
    assert limiter.await_count == 2


async def test_password_reset_confirm_rate_limit_sets_retry_after(client: AsyncClient, monkeypatch) -> None:
    limiter = AsyncMock(
        side_effect=[RateLimitResult(True, 59, 420), RateLimitResult(False, 0, 420)]
    )
    monkeypatch.setattr(redis_services, "check_rate_limit", limiter)
    response = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={
            "token": "x" * 48,
            "password": "Replacement-Password-2026!",
            "confirmPassword": "Replacement-Password-2026!",
        },
    )
    assert response.status_code == 429
    assert response.headers["retry-after"] == "420"
    assert response.json()["error"]["message"] == "Too many password reset attempts. Try again later."
    assert limiter.await_count == 2


async def test_password_reset_schema_rejects_weak_or_mismatched_password(client: AsyncClient) -> None:
    weak = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": "x" * 48, "password": "short", "confirmPassword": "short"},
    )
    assert weak.status_code == 422

    mismatch = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={
            "token": "x" * 48,
            "password": "Replacement-Password-2026!",
            "confirmPassword": "Different-Password-2026!",
        },
    )
    assert mismatch.status_code == 422
