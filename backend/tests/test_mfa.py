from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

from httpx import AsyncClient
from sqlalchemy import select

from northstar_api.database import SessionFactory
from northstar_api.email_verification import EmailVerificationState
from northstar_api.mfa import MFARecoveryCode, MFASetting
from northstar_api.models import Role, User
from northstar_api.security import create_mfa_challenge_token
from northstar_api.services.mfa import totp_code
from northstar_api.services.rate_limit import RateLimitResult, redis_services


def signup_payload(seed: str, email: str, password: str) -> dict[str, object]:
    return {
        "name": "MFA Owner",
        "email": email,
        "password": password,
        "organizationName": f"MFA Organization {seed}",
        "termsAccepted": True,
        "privacyAccepted": True,
    }


async def verified_signup(client: AsyncClient) -> tuple[str, str, str]:
    seed = uuid.uuid4().hex[:10]
    email = f"mfa-{seed}@example.com"
    password = "MFA-Password-2026!"
    response = await client.post("/api/v1/auth/signup", json=signup_payload(seed, email, password))
    assert response.status_code == 201, response.text
    access_token = response.json()["accessToken"]

    async with SessionFactory() as session:
        user = await session.scalar(select(User).where(User.email == email))
        assert user is not None
        verification = await session.get(EmailVerificationState, user.id)
        assert verification is not None
        verification.verified_at = datetime.now(UTC)
        await session.commit()

    return email, password, access_token


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_mfa_full_lifecycle_rotates_sessions_and_uses_one_time_factors(client: AsyncClient) -> None:
    email, password, original_access = await verified_signup(client)

    status_before = await client.get("/api/v1/auth/mfa/status", headers=auth(original_access))
    assert status_before.status_code == 200, status_before.text
    assert status_before.json() == {
        "configured": False,
        "enabled": False,
        "confirmedAt": None,
        "unusedRecoveryCodes": 0,
    }

    wrong_password = await client.post(
        "/api/v1/auth/mfa/setup",
        headers=auth(original_access),
        json={"currentPassword": "Wrong-MFA-Password-2026!"},
    )
    assert wrong_password.status_code == 400
    assert wrong_password.json()["error"]["message"] == "Current password is incorrect"

    setup = await client.post(
        "/api/v1/auth/mfa/setup",
        headers=auth(original_access),
        json={"currentPassword": password},
    )
    assert setup.status_code == 200, setup.text
    assert setup.headers["cache-control"] == "no-store"
    assert setup.headers["pragma"] == "no-cache"
    setup_payload = setup.json()
    secret = setup_payload["secret"]
    recovery_codes = setup_payload["recoveryCodes"]
    assert setup_payload["otpauthUri"].startswith("otpauth://totp/")
    assert len(recovery_codes) == 10
    assert len(set(recovery_codes)) == 10

    async with SessionFactory() as session:
        user = await session.scalar(select(User).where(User.email == email))
        assert user is not None
        setting = await session.get(MFASetting, user.id)
        assert setting is not None
        assert setting.secret_ciphertext != secret.encode("ascii")
        persisted_recovery_codes = list(
            await session.scalars(select(MFARecoveryCode).where(MFARecoveryCode.user_id == user.id))
        )
        assert len(persisted_recovery_codes) == 10
        assert all(item.code_hash not in recovery_codes for item in persisted_recovery_codes)

    counter = int(datetime.now(UTC).timestamp()) // 30
    setup_code = totp_code(secret, counter)
    confirmed = await client.post(
        "/api/v1/auth/mfa/confirm",
        headers=auth(original_access),
        json={"code": setup_code},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.headers["cache-control"] == "no-store"
    confirmed_access = confirmed.json()["accessToken"]
    assert confirmed_access != original_access

    stale_after_enable = await client.get("/api/v1/auth/mfa/status", headers=auth(original_access))
    assert stale_after_enable.status_code == 401
    assert stale_after_enable.json()["error"]["message"] == "Session credentials changed; sign in again"

    enabled_status = await client.get("/api/v1/auth/mfa/status", headers=auth(confirmed_access))
    assert enabled_status.status_code == 200
    assert enabled_status.json()["enabled"] is True
    assert enabled_status.json()["unusedRecoveryCodes"] == 10

    password_login = await client.post(
        "/api/v1/auth/login",
        json={"email": email.upper(), "password": password},
    )
    assert password_login.status_code == 200, password_login.text
    challenge = password_login.json()
    assert challenge["mfaRequired"] is True
    assert challenge["challengeToken"]
    assert "accessToken" not in challenge
    assert "refreshToken" not in challenge
    assert password_login.headers["cache-control"] == "no-store"

    replay_setup_code = await client.post(
        "/api/v1/auth/mfa/verify",
        json={"challengeToken": challenge["challengeToken"], "code": setup_code},
    )
    assert replay_setup_code.status_code == 401
    assert replay_setup_code.json()["error"]["message"] == "Invalid or already used authentication code"

    completed = await client.post(
        "/api/v1/auth/mfa/verify",
        json={"challengeToken": challenge["challengeToken"], "recoveryCode": recovery_codes[0]},
    )
    assert completed.status_code == 200, completed.text
    mfa_access = completed.json()["accessToken"]
    assert mfa_access
    assert completed.headers["cache-control"] == "no-store"

    second_login = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert second_login.status_code == 200
    second_challenge = second_login.json()["challengeToken"]
    reused_recovery = await client.post(
        "/api/v1/auth/mfa/verify",
        json={"challengeToken": second_challenge, "recoveryCode": recovery_codes[0]},
    )
    assert reused_recovery.status_code == 401
    assert reused_recovery.json()["error"]["message"] == "Invalid or already used recovery code"

    regenerated = await client.post(
        "/api/v1/auth/mfa/recovery-codes",
        headers=auth(mfa_access),
        json={"currentPassword": password, "recoveryCode": recovery_codes[1]},
    )
    assert regenerated.status_code == 200, regenerated.text
    assert regenerated.headers["cache-control"] == "no-store"
    assert regenerated.headers["pragma"] == "no-cache"
    new_recovery_codes = regenerated.json()["recoveryCodes"]
    assert len(new_recovery_codes) == 10
    assert not set(new_recovery_codes).intersection(recovery_codes)

    old_code_after_regeneration = await client.post(
        "/api/v1/auth/mfa/verify",
        json={"challengeToken": second_challenge, "recoveryCode": recovery_codes[2]},
    )
    assert old_code_after_regeneration.status_code == 401

    disabled = await client.request(
        "DELETE",
        "/api/v1/auth/mfa",
        headers=auth(mfa_access),
        json={"currentPassword": password, "recoveryCode": new_recovery_codes[0]},
    )
    assert disabled.status_code == 200, disabled.text
    disabled_access = disabled.json()["accessToken"]
    assert disabled_access != mfa_access

    stale_after_disable = await client.get("/api/v1/auth/mfa/status", headers=auth(mfa_access))
    assert stale_after_disable.status_code == 401

    disabled_status = await client.get("/api/v1/auth/mfa/status", headers=auth(disabled_access))
    assert disabled_status.status_code == 200
    assert disabled_status.json()["configured"] is False
    assert disabled_status.json()["enabled"] is False
    assert disabled_status.json()["unusedRecoveryCodes"] == 0

    ordinary_login = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert ordinary_login.status_code == 200
    assert ordinary_login.json()["accessToken"]
    assert "mfaRequired" not in ordinary_login.json()


async def test_mfa_challenge_rate_limit_returns_retry_after(client: AsyncClient, monkeypatch) -> None:
    challenge_token, _ = create_mfa_challenge_token(
        uuid.uuid4(),
        uuid.uuid4(),
        Role.OWNER,
        credential_version=0,
    )
    limiter = AsyncMock(return_value=RateLimitResult(False, 0, 180))
    monkeypatch.setattr(redis_services, "check_rate_limit", limiter)

    response = await client.post(
        "/api/v1/auth/mfa/verify",
        json={"challengeToken": challenge_token, "code": "123456"},
    )

    assert response.status_code == 429
    assert response.headers["retry-after"] == "180"
    assert response.json()["error"]["message"] == "Too many MFA attempts. Sign in again."
    limiter.assert_awaited_once()


async def test_mfa_verify_requires_exactly_one_factor(client: AsyncClient) -> None:
    no_factor = await client.post(
        "/api/v1/auth/mfa/verify",
        json={"challengeToken": "x" * 48},
    )
    assert no_factor.status_code == 422

    both_factors = await client.post(
        "/api/v1/auth/mfa/verify",
        json={"challengeToken": "x" * 48, "code": "123456", "recoveryCode": "ABCD-EFGH-JKLM"},
    )
    assert both_factors.status_code == 422
