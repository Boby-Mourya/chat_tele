from __future__ import annotations

from uuid import UUID, uuid4

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from northstar_api.database import SessionFactory
from northstar_api.lead_crm.channel_models import ChannelOutboundDelivery
from northstar_api.lead_crm.channel_providers import MetaMessagingConnector
from northstar_api.lead_crm.channels import ChannelConnectionContext
from northstar_api.lead_crm.domain import ChannelProvider
from northstar_api.models import Agent, Channel, Conversation, Message
from northstar_api.routers.conversations import _instagram_recipient_id
from northstar_api.services.instagram import (
    INSTAGRAM_TEXT_LIMIT,
    InstagramAPIError,
    InstagramMessagingClient,
    instagram_client,
    normalize_instagram_api_version,
    split_instagram_text,
)
from northstar_api.workers.instagram_tasks import instagram_thread_lock_key, send_instagram_message
from northstar_api.workers.job_dispatcher import whatsapp_dispatch_failure_state


def _conversation(visitor_id: str) -> Conversation:
    return Conversation(
        tenant_id=uuid4(),
        workspace_id=uuid4(),
        agent_id=uuid4(),
        visitor_id=visitor_id,
        visitor_name="Instagram user",
        channel=Channel.API,
    )


def _instagram_context() -> ChannelConnectionContext:
    return ChannelConnectionContext(
        tenant_id=uuid4(),
        connection_id=uuid4(),
        provider=ChannelProvider.INSTAGRAM,
        configuration={"instagramAccountId": "123456", "apiVersion": "v26.0"},
        credentials={
            "access_token": "instagram-token",
            "app_secret": "meta-app-secret",
            "verify_token": "webhook-verify-token",
        },
    )


def test_instagram_api_version_is_pinned_but_configurable() -> None:
    assert normalize_instagram_api_version(None) == "v26.0"
    assert normalize_instagram_api_version("26.0") == "v26.0"
    assert normalize_instagram_api_version("v25.0") == "v25.0"
    with pytest.raises(InstagramAPIError):
        normalize_instagram_api_version("latest")


def test_instagram_text_splitter_preserves_content_and_limit() -> None:
    source = ("northstar " * 400).strip()
    chunks = split_instagram_text(source)
    assert len(chunks) >= 2
    assert all(1 <= len(chunk) <= INSTAGRAM_TEXT_LIMIT for chunk in chunks)
    assert " ".join(" ".join(chunks).split()) == " ".join(source.split())
    assert split_instagram_text("   ") == []


def test_instagram_conversation_identity_is_exact_and_safe() -> None:
    assert _instagram_recipient_id(_conversation("instagram:17890001")) == "17890001"
    assert _instagram_recipient_id(_conversation("api:17890001")) is None
    assert _instagram_recipient_id(_conversation("facebook_messenger:17890001")) is None
    assert _instagram_recipient_id(_conversation("instagram:@username")) is None
    assert _instagram_recipient_id(_conversation("instagram:")) is None


def test_instagram_thread_lock_is_connection_and_recipient_scoped() -> None:
    connection_id = uuid4()
    first = instagram_thread_lock_key(connection_id, "1789")
    assert first == instagram_thread_lock_key(connection_id, "1789")
    assert first != instagram_thread_lock_key(connection_id, "1790")
    assert first != instagram_thread_lock_key(uuid4(), "1789")


def test_dispatch_backoff_contract_is_reused_without_changing_whatsapp() -> None:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    attempts, state, retry_at, delay = whatsapp_dispatch_failure_state(0, 8, now)
    assert attempts == 1
    assert state == "failed"
    assert retry_at is not None
    assert delay >= 1


@pytest.mark.anyio
async def test_instagram_health_check_validates_professional_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def get_account(
        access_token: str,
        *,
        account_id: str,
        api_version: object,
    ) -> dict[str, object]:
        assert access_token == "instagram-token"
        assert account_id == "123456"
        assert api_version == "v26.0"
        return {"id": account_id, "username": "northstar_academy"}

    monkeypatch.setattr(instagram_client, "get_account", get_account)
    result = await MetaMessagingConnector(ChannelProvider.INSTAGRAM).health_check(_instagram_context())
    assert result == {"status": "healthy", "username": "northstar_academy"}


@pytest.mark.anyio
async def test_instagram_health_check_rejects_incomplete_credentials() -> None:
    context = ChannelConnectionContext(
        tenant_id=uuid4(),
        connection_id=uuid4(),
        provider=ChannelProvider.INSTAGRAM,
        configuration={"instagramAccountId": "123456"},
        credentials={"app_secret": "only-one-secret"},
    )
    result = await MetaMessagingConnector(ChannelProvider.INSTAGRAM).health_check(context)
    assert result == {"status": "configuration_error"}


@pytest.mark.anyio
async def test_instagram_client_uses_send_api_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def request(self, method: str, url: str, **kwargs: object) -> httpx.Response:
            captured.update(method=method, url=url, **kwargs)
            return httpx.Response(200, json={"recipient_id": "1789", "message_id": "mid.123"})

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    result = await InstagramMessagingClient().send_text(
        "instagram-token",
        account_id="123456",
        recipient_id="1789",
        text="hello",
        api_version="v26.0",
    )
    assert result == "mid.123"
    assert captured["method"] == "POST"
    assert captured["url"] == "https://graph.instagram.com/v26.0/123456/messages"
    assert captured["json"] == {"recipient": {"id": "1789"}, "message": {"text": "hello"}}
    assert captured["headers"] == {
        "Authorization": "Bearer instagram-token",
        "Content-Type": "application/json",
    }


@pytest.mark.anyio
async def test_instagram_client_classifies_auth_and_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = [
        httpx.Response(
            400,
            json={"error": {"code": 190, "message": "Invalid OAuth access token"}},
        ),
        httpx.Response(
            429,
            headers={"Retry-After": "7"},
            json={"error": {"code": 4, "message": "Application request limit reached"}},
        ),
    ]

    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def request(self, *args: object, **kwargs: object) -> httpx.Response:
            return responses.pop(0)

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    client = InstagramMessagingClient()

    with pytest.raises(InstagramAPIError) as auth_error:
        await client.get_account("bad", account_id="123456")
    assert auth_error.value.requires_reconnect is True
    assert auth_error.value.retryable is False

    with pytest.raises(InstagramAPIError) as rate_error:
        await client.send_text("token", account_id="123456", recipient_id="1789", text="hello")
    assert rate_error.value.retryable is True
    assert rate_error.value.retry_after_seconds == 7


@pytest.mark.anyio
async def test_conversation_reply_creates_durable_instagram_delivery_and_preserves_api_reply(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CRM_CREDENTIAL_ENCRYPTION_KEY", "instagram-test-encryption-key")
    monkeypatch.setattr(send_instagram_message, "apply_async", lambda *args, **kwargs: None)

    workspace_response = await client.get("/api/v1/workspace", headers=auth_headers)
    assert workspace_response.status_code == 200, workspace_response.text
    workspace = workspace_response.json()
    tenant_id = UUID(workspace["tenantId"])
    workspace_id = UUID(workspace["id"])
    agent_id = uuid4()
    instagram_conversation_id = uuid4()
    api_conversation_id = uuid4()

    async with SessionFactory() as session:
        session.add(
            Agent(
                id=agent_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                name=f"Instagram test {agent_id.hex[:8]}",
            )
        )
        session.add_all(
            [
                Conversation(
                    id=instagram_conversation_id,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    visitor_id="instagram:17890001",
                    visitor_name="Instagram user",
                    channel=Channel.API,
                ),
                Conversation(
                    id=api_conversation_id,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    visitor_id="api:ordinary-client",
                    visitor_name="API user",
                    channel=Channel.API,
                ),
            ]
        )
        await session.commit()

    connection = await client.post(
        "/api/v1/channels/connections",
        headers=auth_headers,
        json={
            "provider": "instagram",
            "name": f"Instagram {agent_id.hex[:8]}",
            "agentId": str(agent_id),
            "configuration": {
                "agentId": str(agent_id),
                "instagramAccountId": "123456",
                "apiVersion": "v26.0",
            },
            "credentials": {
                "access_token": "instagram-token",
                "app_secret": "meta-app-secret",
                "verify_token": "webhook-verify-token",
            },
        },
    )
    assert connection.status_code == 201, connection.text

    instagram_reply = await client.post(
        f"/api/v1/conversations/{instagram_conversation_id}/messages",
        headers=auth_headers,
        json={"content": "Hello from Northstar"},
    )
    assert instagram_reply.status_code == 201, instagram_reply.text

    api_reply = await client.post(
        f"/api/v1/conversations/{api_conversation_id}/messages",
        headers=auth_headers,
        json={"content": "Local API reply"},
    )
    assert api_reply.status_code == 201, api_reply.text

    async with SessionFactory() as session:
        instagram_message = await session.get(Message, UUID(instagram_reply.json()["id"]))
        api_message = await session.get(Message, UUID(api_reply.json()["id"]))
        assert instagram_message is not None
        assert api_message is not None
        assert instagram_message.finish_reason == "queued"
        assert api_message.finish_reason == "sent"

        deliveries = list(
            await session.scalars(
                select(ChannelOutboundDelivery).where(
                    ChannelOutboundDelivery.tenant_id == tenant_id,
                    ChannelOutboundDelivery.message_id == instagram_message.id,
                )
            )
        )
        assert len(deliveries) == 1
        assert deliveries[0].provider == "instagram"
        assert deliveries[0].recipient_external_id == "17890001"
        assert deliveries[0].status == "queued"

        api_delivery = await session.scalar(
            select(ChannelOutboundDelivery).where(
                ChannelOutboundDelivery.message_id == api_message.id
            )
        )
        assert api_delivery is None
