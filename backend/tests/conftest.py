from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

Path("northstar-test.db").unlink(missing_ok=True)

os.environ.update(
    {
        "APP_ENV": "test",
        "DATABASE_URL": "sqlite+aiosqlite:///./northstar-test.db",
        "REDIS_URL": "redis://127.0.0.1:6399/15",
        "APP_AUTO_CREATE_SCHEMA": "true",
        "JWT_SECRET": "test-only-secret-with-more-than-thirty-two-characters",
        "SEED_ADMIN_EMAIL": "owner@example.com",
        "SEED_ADMIN_PASSWORD": "Correct-Horse-Test-Password-42!",
        "SEED_ADMIN_NAME": "Test Owner",
        "SEED_TENANT_NAME": "Test Workspace",
        "SEED_TENANT_PLAN": "enterprise",
        "ALLOW_DETERMINISTIC_EMBEDDINGS": "true",
        "RATE_LIMIT_FAIL_OPEN": "true",
        "BACKGROUND_DISPATCH_ENABLED": "false",
    }
)

from northstar_api.main import app  # noqa: E402


@pytest.fixture(scope="session")
async def client() -> AsyncIterator[AsyncClient]:
    async with LifespanManager(app, startup_timeout=60, shutdown_timeout=60):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as http:
            yield http


@pytest.fixture(scope="session")
async def session_payload(client: AsyncClient) -> dict:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "Correct-Horse-Test-Password-42!"},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture(scope="session")
async def auth_headers(session_payload: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {session_payload['accessToken']}"}


@pytest.fixture(autouse=True)
async def reset_shared_test_subscription(request) -> AsyncIterator[None]:
    """Prevent a failed plan-specific test from contaminating later API tests."""
    if "client" not in request.fixturenames:
        yield
        return
    from uuid import UUID

    from northstar_api.database import SessionFactory
    from northstar_api.models import Tenant
    from northstar_api.security import decode_token
    from northstar_api.services.subscriptions import set_subscription_state
    from northstar_api.subscriptions import SubscriptionStatus

    headers = request.getfixturevalue("auth_headers")
    tenant_id = UUID(decode_token(headers["Authorization"].removeprefix("Bearer "), "access")["tid"])
    async with SessionFactory() as session:
        tenant = await session.get(Tenant, tenant_id)
        assert tenant is not None
        tenant.plan = "legacy_custom_contract"
        await set_subscription_state(
            session,
            tenant_id=tenant_id,
            plan="legacy_custom_contract",
            status=SubscriptionStatus.ACTIVE,
        )
        await session.commit()
    yield


@pytest.fixture
async def crm_test_plan(client, auth_headers):
    from uuid import UUID

    from northstar_api.database import SessionFactory
    from northstar_api.security import decode_token
    from northstar_api.services.subscriptions import set_subscription_state
    from northstar_api.subscriptions import SubscriptionStatus

    tenant_id = UUID(decode_token(auth_headers["Authorization"].removeprefix("Bearer "), "access")["tid"])
    async with SessionFactory() as session:
        subscription = await set_subscription_state(session, tenant_id=tenant_id)
        original = subscription.plan, subscription.status
        await set_subscription_state(
            session, tenant_id=tenant_id, plan="enterprise", status=SubscriptionStatus.ACTIVE
        )
        await session.commit()
    yield
    async with SessionFactory() as session:
        await set_subscription_state(session, tenant_id=tenant_id, plan=original[0], status=original[1])
        await session.commit()
