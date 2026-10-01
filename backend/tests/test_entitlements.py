from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

from httpx import AsyncClient

from northstar_api.database import SessionFactory
from northstar_api.entitlements import CUSTOM_UNLIMITED_ENTITLEMENT, entitlement_for_plan
from northstar_api.models import KnowledgeKind, KnowledgeStatus
from northstar_api.services.entitlements import _stored_source_bytes
from northstar_api.services.subscriptions import set_subscription_state
from northstar_api.subscriptions import SubscriptionStatus


def test_plan_catalog_preserves_existing_business_limits_and_custom_compatibility() -> None:
    business = entitlement_for_plan("business")
    assert business.agent_limit == 10
    assert business.member_limit == 20
    assert business.conversation_limit_monthly == 5_000
    assert business.crm_enabled is True
    assert business.api_enabled is True
    assert business.white_label_enabled is True

    custom = entitlement_for_plan("legacy_custom_contract")
    assert custom is CUSTOM_UNLIMITED_ENTITLEMENT
    assert custom.workspace_limit is None
    assert custom.agent_limit is None
    assert custom.member_limit is None
    assert custom.allowed_channels


def test_existing_knowledge_storage_labels_are_accounted_without_schema_replacement() -> None:
    assert _stored_source_bytes(SimpleNamespace(content="hello", size_label="Queued")) == 5
    assert _stored_source_bytes(SimpleNamespace(content=None, size_label="1.5 KB")) == 1536
    assert _stored_source_bytes(SimpleNamespace(content=None, size_label="2.0 MB")) == 2 * 1024**2
    assert _stored_source_bytes(SimpleNamespace(content=None, size_label="Queued")) == 0

    pending_remote = SimpleNamespace(
        content=None,
        size_label="Queued",
        kind=KnowledgeKind.URL,
        status=KnowledgeStatus.PROCESSING,
    )
    failed_remote = SimpleNamespace(
        content=None,
        size_label="Queued",
        kind=KnowledgeKind.URL,
        status=KnowledgeStatus.FAILED,
    )
    assert _stored_source_bytes(pending_remote) > 0
    assert _stored_source_bytes(failed_remote) == 0


async def test_entitlements_endpoint_reports_measured_usage_and_limits(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    response = await client.get("/api/v1/billing/entitlements", headers=auth_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["plan"]
    assert payload["subscriptionStatus"] in {"trial", "active", "past_due", "suspended", "cancelled"}
    assert set(payload["limits"]) == {
        "workspaces",
        "agents",
        "members",
        "conversationsMonthly",
        "tokensMonthly",
        "storageBytes",
    }
    assert set(payload["usage"]) == {
        "workspaces",
        "agents",
        "members",
        "pendingMemberSeats",
        "conversationsMonthly",
        "tokensMonthly",
        "storageBytes",
    }
    assert set(payload["features"]) == {"allowedChannels", "crm", "api", "whiteLabel"}
    for value in payload["usage"].values():
        assert isinstance(value, int) and value >= 0


async def test_starter_plan_enforces_workspace_channel_crm_and_white_label_boundaries(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    workspace_response = await client.get("/api/v1/workspace", headers=auth_headers)
    assert workspace_response.status_code == 200, workspace_response.text
    tenant_id = UUID(workspace_response.json()["tenantId"])

    async with SessionFactory() as session:
        current = await set_subscription_state(session, tenant_id=tenant_id)
        original_plan = current.plan
        original_status = current.status
        await set_subscription_state(
            session,
            tenant_id=tenant_id,
            plan="starter",
            status=SubscriptionStatus.ACTIVE,
        )
        await session.commit()

    try:
        entitlements = await client.get("/api/v1/billing/entitlements", headers=auth_headers)
        assert "telegram" in entitlements.json()["features"]["allowedChannels"]
        created = await client.post(
            "/api/v1/agents", headers=auth_headers,
            json={"name": "Starter Telegram", "purpose": "education", "deploymentChannel": "telegram"},
        )
        assert created.status_code == 201, created.text
        agent = created.json()
        assert agent["appearance"]["deploymentChannel"] == "telegram"
        assert agent["status"] == "draft"
        connection = await client.post(
            "/api/v1/channels/connections", headers=auth_headers,
            json={"provider": "telegram", "name": "Starter Telegram connection", "agentId": agent["id"]},
        )
        assert connection.status_code == 201, connection.text
        await client.delete(f"/api/v1/channels/connections/{connection.json()['id']}", headers=auth_headers)
        removed = await client.delete(f"/api/v1/agents/{agent['id']}", headers=auth_headers)
        assert removed.status_code == 204, removed.text

        workspace_create = await client.post(
            "/api/v1/workspaces",
            headers=auth_headers,
            json={"name": "Second workspace", "slug": "second-workspace"},
        )
        assert workspace_create.status_code == 409, workspace_create.text
        assert "workspace" in workspace_create.json()["error"]["message"].lower()
        assert "limit" in workspace_create.json()["error"]["message"].lower()

        whatsapp = await client.post(
            "/api/v1/channels/connections",
            headers=auth_headers,
            json={"provider": "whatsapp", "name": "Starter WhatsApp"},
        )
        assert whatsapp.status_code == 403, whatsapp.text
        assert "not available" in whatsapp.json()["error"]["message"].lower()

        crm = await client.post(
            "/api/v1/crm/connections",
            headers=auth_headers,
            json={"provider": "zoho", "name": "Starter CRM"},
        )
        assert crm.status_code == 403, crm.text
        assert "not available" in crm.json()["error"]["message"].lower()

        white_label = await client.patch(
            "/api/v1/workspace",
            headers=auth_headers,
            json={"whiteLabel": {"companyName": "Starter Brand"}},
        )
        assert white_label.status_code == 403, white_label.text
        assert "white label" in white_label.json()["error"]["message"].lower()
    finally:
        async with SessionFactory() as session:
            await set_subscription_state(
                session,
                tenant_id=tenant_id,
                plan=original_plan,
                status=original_status,
            )
            await session.commit()


async def test_suspended_subscription_blocks_new_capacity_without_removing_reads(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    workspace_response = await client.get("/api/v1/workspace", headers=auth_headers)
    assert workspace_response.status_code == 200, workspace_response.text
    tenant_id = UUID(workspace_response.json()["tenantId"])

    async with SessionFactory() as session:
        current = await set_subscription_state(session, tenant_id=tenant_id)
        original_plan = current.plan
        original_status = current.status
        await set_subscription_state(
            session,
            tenant_id=tenant_id,
            status=SubscriptionStatus.SUSPENDED,
        )
        await session.commit()

    try:
        still_readable = await client.get("/api/v1/workspace", headers=auth_headers)
        assert still_readable.status_code == 200, still_readable.text

        blocked = await client.post(
            "/api/v1/workspace/api-keys",
            headers=auth_headers,
            json={"name": "Blocked while suspended"},
        )
        assert blocked.status_code == 403, blocked.text
        assert "suspended" in blocked.json()["error"]["message"].lower()
    finally:
        async with SessionFactory() as session:
            await set_subscription_state(
                session,
                tenant_id=tenant_id,
                plan=original_plan,
                status=original_status,
            )
            await session.commit()
