from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from northstar_api.database import SessionFactory
from northstar_api.email_verification import EmailVerificationState, EmailVerificationToken
from northstar_api.models import (
    Role,
    Tenant,
    TenantMembership,
    User,
    Workspace,
    WorkspaceMembership,
    WorkspaceRole,
)
from northstar_api.security import verify_password
from northstar_api.services.rate_limit import RateLimitResult, SessionStoreUnavailable, redis_services


async def test_signup_provisions_owner_tenant_workspace_and_session(client: AsyncClient) -> None:
    seed = uuid.uuid4().hex[:10]
    email = f"Signup.Owner.{seed}@Example.com"
    normalized_email = email.lower()
    credential = "Signup-Password-2026!"
    payload = {
        "name": "  Signup   Owner  ",
        "email": email,
        "password": credential,
        "organizationName": f"Northstar Signup {seed}",
        "termsAccepted": True,
        "privacyAccepted": True,
    }

    response = await client.post("/api/v1/auth/signup", json=payload)

    assert response.status_code == 201, response.text
    session_payload = response.json()
    assert session_payload["accessToken"]
    assert session_payload["refreshToken"]
    assert session_payload["expiresAt"]
    assert session_payload["user"]["name"] == "Signup Owner"
    assert session_payload["user"]["email"] == normalized_email
    assert session_payload["user"]["role"] == "owner"
    assert session_payload["user"]["emailVerified"] is False
    assert response.headers["cache-control"] == "no-store"
    assert "HttpOnly" in response.headers["set-cookie"]

    async with SessionFactory() as session:
        user = await session.scalar(select(User).where(User.email == normalized_email))
        assert user is not None
        assert user.password_hash != credential
        assert verify_password(credential, user.password_hash)

        verification_state = await session.get(EmailVerificationState, user.id)
        assert verification_state is not None
        assert verification_state.verified_at is None
        token_count = int(
            await session.scalar(
                select(func.count())
                .select_from(EmailVerificationToken)
                .where(EmailVerificationToken.user_id == user.id)
            )
            or 0
        )
        assert token_count == 1

        tenant_membership = await session.scalar(
            select(TenantMembership).where(TenantMembership.user_id == user.id)
        )
        assert tenant_membership is not None
        assert tenant_membership.role is Role.OWNER

        tenant = await session.scalar(select(Tenant).where(Tenant.id == tenant_membership.tenant_id))
        assert tenant is not None
        assert tenant.name == payload["organizationName"]
        assert tenant.plan == "starter"
        assert tenant.settings_json["signup"]["source"] == "self_service"
        assert tenant.settings_json["signup"]["termsAccepted"] is True
        assert tenant.settings_json["signup"]["privacyAccepted"] is True
        assert tenant.settings_json["signup"]["acceptedAt"]

        workspace_membership = await session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.user_id == user.id,
                WorkspaceMembership.tenant_id == tenant.id,
            )
        )
        assert workspace_membership is not None
        assert workspace_membership.role is WorkspaceRole.ADMIN
        assert workspace_membership.all_agents_access is True

        workspace = await session.scalar(
            select(Workspace).where(Workspace.id == workspace_membership.workspace_id)
        )
        assert workspace is not None
        assert workspace.name == payload["organizationName"]
        assert workspace.slug == "default"
        assert workspace.created_by == user.id

    headers = {"Authorization": f"Bearer {session_payload['accessToken']}"}
    workspaces = await client.get("/api/v1/workspaces", headers=headers)
    assert workspaces.status_code == 403, workspaces.text
    assert workspaces.json()["error"]["message"] == "Email verification required"

    signed_in = await client.post(
        "/api/v1/auth/login",
        json={"email": email.upper(), "password": credential},
    )
    assert signed_in.status_code == 200, signed_in.text
    assert signed_in.json()["user"]["id"] == session_payload["user"]["id"]
    assert signed_in.json()["user"]["role"] == "owner"
    assert signed_in.json()["user"]["emailVerified"] is False


async def test_signup_duplicate_email_is_case_insensitive_and_does_not_create_second_account(
    client: AsyncClient,
) -> None:
    seed = uuid.uuid4().hex[:10]
    email = f"duplicate-{seed}@example.com"
    first = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "First Owner",
            "email": email,
            "password": "Duplicate-Password-2026!",
            "organizationName": f"First Organization {seed}",
            "termsAccepted": True,
            "privacyAccepted": True,
        },
    )
    assert first.status_code == 201, first.text

    duplicate = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Second Owner",
            "email": email.upper(),
            "password": "Duplicate-Password-2026!",
            "organizationName": f"Second Organization {seed}",
            "termsAccepted": True,
            "privacyAccepted": True,
        },
    )
    assert duplicate.status_code == 409, duplicate.text
    assert duplicate.json()["error"]["message"] == "An account with this email already exists"

    async with SessionFactory() as session:
        user = await session.scalar(select(User).where(User.email == email))
        assert user is not None
        tenant_memberships = int(
            await session.scalar(
                select(func.count()).select_from(TenantMembership).where(TenantMembership.user_id == user.id)
            )
            or 0
        )
        workspace_memberships = int(
            await session.scalar(
                select(func.count())
                .select_from(WorkspaceMembership)
                .where(WorkspaceMembership.user_id == user.id)
            )
            or 0
        )
    assert tenant_memberships == 1
    assert workspace_memberships == 1


async def test_signup_rate_limit_is_generic_and_sets_retry_after(client: AsyncClient, monkeypatch) -> None:
    limiter = AsyncMock(
        side_effect=[RateLimitResult(True, 29, 1800), RateLimitResult(False, 0, 1800)]
    )
    monkeypatch.setattr(redis_services, "check_rate_limit", limiter)
    seed = uuid.uuid4().hex[:10]

    response = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Rate Limited Owner",
            "email": f"rate-limited-{seed}@example.com",
            "password": "Rate-Limit-Password-2026!",
            "organizationName": f"Rate Limited Organization {seed}",
            "termsAccepted": True,
            "privacyAccepted": True,
        },
    )

    assert response.status_code == 429, response.text
    assert response.headers["retry-after"] == "1800"
    assert response.json()["error"]["message"] == "Too many account creation attempts. Try again later."
    assert limiter.await_count == 2


async def test_signup_session_store_failure_rolls_back_account(client: AsyncClient, monkeypatch) -> None:
    remember = AsyncMock(side_effect=SessionStoreUnavailable("Session store unavailable"))
    monkeypatch.setattr(redis_services, "remember_refresh_family", remember)
    seed = uuid.uuid4().hex[:10]
    email = f"rollback-{seed}@example.com"
    organization_name = f"Rollback Organization {seed}"

    response = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Rollback Owner",
            "email": email,
            "password": "Rollback-Password-2026!",
            "organizationName": organization_name,
            "termsAccepted": True,
            "privacyAccepted": True,
        },
    )

    assert response.status_code == 503, response.text
    assert remember.await_count == 1
    async with SessionFactory() as session:
        user_count = int(
            await session.scalar(select(func.count()).select_from(User).where(User.email == email)) or 0
        )
        tenant_count = int(
            await session.scalar(
                select(func.count()).select_from(Tenant).where(Tenant.name == organization_name)
            )
            or 0
        )
    assert user_count == 0
    assert tenant_count == 0


@pytest.mark.parametrize(
    ("patch", "field_fragment"),
    [
        ({"termsAccepted": False}, "termsAccepted"),
        ({"privacyAccepted": False}, "privacyAccepted"),
        ({"password": "too-short"}, "password"),
    ],
)
async def test_signup_requires_legal_acceptance_and_new_account_password_policy(
    client: AsyncClient,
    patch: dict[str, object],
    field_fragment: str,
) -> None:
    seed = uuid.uuid4().hex[:10]
    payload: dict[str, object] = {
        "name": "Validation Owner",
        "email": f"validation-{seed}@example.com",
        "password": "Validation-Password-2026!",
        "organizationName": f"Validation Organization {seed}",
        "termsAccepted": True,
        "privacyAccepted": True,
    }
    payload.update(patch)

    response = await client.post("/api/v1/auth/signup", json=payload)

    assert response.status_code == 422, response.text
    fields = response.json()["error"]["fields"]
    assert any(field_fragment in item["field"] for item in fields)
