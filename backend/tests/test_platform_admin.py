from __future__ import annotations

from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy import delete

from northstar_api.database import SessionFactory
from northstar_api.models import Tenant
from northstar_api.routers.platform_admin import platform_admin_emails
from northstar_api.services.rate_limit import redis_services
from northstar_api.subscriptions import SubscriptionStatus, TenantSubscription


def _enable(monkeypatch, email: str) -> None:
    monkeypatch.setenv("PLATFORM_ADMIN_EMAILS", f'["{email.upper()}"]')


def test_platform_admin_allowlist_parser_is_explicit_and_case_insensitive() -> None:
    assert platform_admin_emails("") == frozenset()
    assert platform_admin_emails(" Admin@Example.com , ops@example.com ") == frozenset(
        {"admin@example.com", "ops@example.com"}
    )
    assert platform_admin_emails('["Admin@Example.com", "OPS@example.com"]') == frozenset(
        {"admin@example.com", "ops@example.com"}
    )
    assert platform_admin_emails("[not-json") == frozenset()


async def test_platform_admin_is_disabled_without_explicit_allowlist(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    monkeypatch.delenv("PLATFORM_ADMIN_EMAILS", raising=False)
    response = await client.get("/api/v1/platform-admin/access", headers=auth_headers)
    assert response.status_code == 403, response.text
    assert "not enabled" in response.json()["error"]["message"].lower()


async def test_platform_admin_reads_across_tenants_without_mutating_customer_data(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_payload: dict,
    monkeypatch,
) -> None:
    email = session_payload["user"]["email"]
    _enable(monkeypatch, email)
    external_tenant_id = uuid4()
    external_slug = f"platform-support-{uuid4().hex[:10]}"

    async with SessionFactory() as session:
        external = Tenant(
            id=external_tenant_id,
            slug=external_slug,
            name="External Support Tenant",
            plan="professional",
        )
        session.add(external)
        session.add(
            TenantSubscription(
                tenant_id=external_tenant_id,
                plan="professional",
                status=SubscriptionStatus.PAST_DUE,
            )
        )
        await session.commit()

    try:
        access = await client.get("/api/v1/platform-admin/access", headers=auth_headers)
        assert access.status_code == 200, access.text
        assert access.json()["authorized"] is True
        assert access.json()["email"].lower() == email.lower()

        overview = await client.get("/api/v1/platform-admin/overview", headers=auth_headers)
        assert overview.status_code == 200, overview.text
        payload = overview.json()
        assert payload["tenants"] >= 2
        assert payload["subscriptions"]["pastDue"] >= 1
        assert payload["operations"]["status"] in {"healthy", "degraded"}

        tenants = await client.get(
            "/api/v1/platform-admin/tenants",
            headers=auth_headers,
            params={"search": external_slug},
        )
        assert tenants.status_code == 200, tenants.text
        items = tenants.json()["items"]
        assert len(items) == 1
        assert items[0]["id"] == str(external_tenant_id)
        assert items[0]["plan"] == "professional"
        assert items[0]["subscriptionStatus"] == "past_due"

        detail = await client.get(
            f"/api/v1/platform-admin/tenants/{external_tenant_id}",
            headers=auth_headers,
        )
        assert detail.status_code == 200, detail.text
        assert detail.json()["slug"] == external_slug
        assert detail.json()["workspaces"] == []
        assert detail.json()["users"] == []

        read_only = await client.post(
            "/api/v1/platform-admin/tenants",
            headers=auth_headers,
            json={"name": "Must not exist"},
        )
        assert read_only.status_code == 405, read_only.text

        async with SessionFactory() as session:
            stored = await session.get(Tenant, external_tenant_id)
            assert stored is not None
            assert stored.name == "External Support Tenant"
            assert stored.plan == "professional"
    finally:
        async with SessionFactory() as session:
            await session.execute(
                delete(TenantSubscription).where(TenantSubscription.tenant_id == external_tenant_id)
            )
            await session.execute(delete(Tenant).where(Tenant.id == external_tenant_id))
            await session.commit()


async def test_platform_admin_exposes_server_owned_entitlements(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_payload: dict,
    monkeypatch,
) -> None:
    _enable(monkeypatch, session_payload["user"]["email"])
    organization_headers = {key: value for key, value in auth_headers.items() if key.lower() != "x-workspace-id"}
    response = await client.get("/api/v1/platform-admin/entitlements", headers=organization_headers)
    assert response.status_code == 200, response.text
    values = {item["plan"]: item for item in response.json()}
    assert {"free", "starter", "professional", "business", "enterprise"} <= values.keys()
    assert values["starter"]["whiteLabelEnabled"] is False
    assert values["business"]["customDomainEnabled"] is True


async def test_platform_admin_exposes_non_secret_runtime_configuration(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_payload: dict,
    monkeypatch,
) -> None:
    _enable(monkeypatch, session_payload["user"]["email"])
    response = await client.get("/api/v1/platform-admin/configuration", headers=auth_headers)
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["appApiPrefix"] == "/api/v1"
    assert value["platformImpersonationTtlMinutes"] == 15
    assert "databaseUrl" not in value
    assert "jwtSecret" not in value


async def test_platform_admin_rejects_workspace_api_keys(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_payload: dict,
    monkeypatch,
) -> None:
    _enable(monkeypatch, session_payload["user"]["email"])
    created = await client.post(
        "/api/v1/workspace/api-keys",
        headers=auth_headers,
        json={"name": "Platform admin isolation key"},
    )
    assert created.status_code == 201, created.text
    secret = created.json()["secret"]
    key_id = created.json()["id"]
    try:
        denied = await client.get(
            "/api/v1/platform-admin/overview",
            headers={"Authorization": f"Bearer {secret}"},
        )
        assert denied.status_code == 403, denied.text
        assert "API keys" in denied.json()["error"]["message"]
    finally:
        revoked = await client.delete(
            f"/api/v1/workspace/api-keys/{key_id}",
            headers=auth_headers,
        )
        assert revoked.status_code == 204, revoked.text


async def test_platform_admin_tenant_detail_returns_not_found_for_unknown_tenant(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_payload: dict,
    monkeypatch,
) -> None:
    _enable(monkeypatch, session_payload["user"]["email"])
    missing = await client.get(
        f"/api/v1/platform-admin/tenants/{uuid4()}",
        headers=auth_headers,
    )
    assert missing.status_code == 404, missing.text
    assert missing.json()["error"]["message"] == "Tenant not found"


async def test_platform_admin_impersonation_requires_membership_and_is_tagged(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_payload: dict,
    monkeypatch,
) -> None:
    _enable(monkeypatch, session_payload["user"]["email"])
    workspaces = await client.get("/api/v1/workspaces", headers=auth_headers)
    assert workspaces.status_code == 200, workspaces.text
    workspace_id = workspaces.json()[0]["id"]
    payload = {
        "tenantId": workspaces.json()[0]["tenantId"],
        "workspaceId": workspace_id,
        "userId": session_payload["user"]["id"],
        "reason": "Investigate customer support issue",
    }
    response = await client.post("/api/v1/platform-admin/impersonation", headers=auth_headers, json=payload)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["tenantId"] == payload["tenantId"]
    assert result["workspaceId"] == workspace_id
    assert result["userId"] == payload["userId"]
    assert result["impersonationId"].startswith("imp_")
    assert result["accessToken"]

    revoked: list[tuple[str, str, int]] = []

    async def fake_set(key: str, value: str, ex: int) -> None:
        revoked.append((key, value, ex))

    monkeypatch.setattr(redis_services.client, "set", fake_set)
    ended = await client.post(
        f"/api/v1/platform-admin/impersonation/{result['impersonationId']}/end",
        headers=auth_headers,
        json={"reason": "Support investigation complete"},
    )
    assert ended.status_code == 204, ended.text
    assert revoked == [(f"northstar:impersonation:revoked:{result['impersonationId']}", "1", 86_400)]

    denied = await client.post(
        "/api/v1/platform-admin/impersonation",
        headers=auth_headers,
        json={**payload, "workspaceId": str(uuid4())},
    )
    assert denied.status_code == 404, denied.text
