from __future__ import annotations

from uuid import UUID, uuid4

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from northstar_api.database import SessionFactory
from northstar_api.lead_crm.channel_models import ChannelOutboundDelivery
from northstar_api.lead_crm.channel_providers import TelegramConnector
from northstar_api.lead_crm.channels import ChannelConnectionContext
from northstar_api.lead_crm.domain import ChannelProvider
from northstar_api.models import Agent, Channel, Conversation, Message
from northstar_api.routers.conversations import _telegram_chat_id
from northstar_api.services.telegram import (
    TELEGRAM_TEXT_LIMIT,
    TelegramAPIError,
    TelegramBotClient,
    split_telegram_text,
    telegram_client,
)
from northstar_api.workers.job_dispatcher import whatsapp_dispatch_failure_state
from northstar_api.workers.telegram_tasks import send_telegram_message, telegram_thread_lock_key


def _conversation(visitor_id: str) -> Conversation:
    return Conversation(
        tenant_id=uuid4(),
        workspace_id=uuid4(),
        agent_id=uuid4(),
        visitor_id=visitor_id,
        visitor_name="Telegram user",
        channel=Channel.API,
    )


def _telegram_context() -> ChannelConnectionContext:
    return ChannelConnectionContext(
        tenant_id=uuid4(),
        connection_id=uuid4(),
        provider=ChannelProvider.TELEGRAM,
        configuration={},
        credentials={"bot_token": "secret-token", "webhook_secret": "webhook-secret"},
    )


def test_telegram_text_splitter_preserves_content_and_limit() -> None:
    source = ("word " * 1800).strip()
    chunks = split_telegram_text(source)
    assert len(chunks) >= 2
    assert all(1 <= len(chunk) <= TELEGRAM_TEXT_LIMIT for chunk in chunks)
    assert " ".join(" ".join(chunks).split()) == " ".join(source.split())
    assert split_telegram_text("   ") == []


def test_telegram_conversation_identity_is_exact_and_safe() -> None:
    assert _telegram_chat_id(_conversation("telegram:123456")) == "123456"
    assert _telegram_chat_id(_conversation("telegram:-100123456")) == "-100123456"
    assert _telegram_chat_id(_conversation("api:123456")) is None
    assert _telegram_chat_id(_conversation("telegram:@username")) is None
    assert _telegram_chat_id(_conversation("telegram:")) is None


def test_outbound_model_is_provider_neutral_and_deduplicates_messages() -> None:
    table = ChannelOutboundDelivery.__table__
    assert table.name == "channel_outbound_deliveries"
    assert "provider" in table.c
    assert "recipient_external_id" in table.c
    assert "provider_message_ids" in table.c
    uniques = {constraint.name for constraint in table.constraints if constraint.name}
    assert "uq_channel_outbound_provider_message" in uniques


def test_telegram_thread_lock_is_connection_and_chat_scoped() -> None:
    connection_id = uuid4()
    first = telegram_thread_lock_key(connection_id, "42")
    assert first == telegram_thread_lock_key(connection_id, "42")
    assert first != telegram_thread_lock_key(connection_id, "43")
    assert first != telegram_thread_lock_key(uuid4(), "42")


def test_dispatch_backoff_contract_can_be_reused_without_changing_whatsapp() -> None:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    attempts, state, retry_at, delay = whatsapp_dispatch_failure_state(0, 8, now)
    assert attempts == 1
    assert state == "failed"
    assert retry_at is not None
    assert delay >= 1


@pytest.mark.anyio
async def test_telegram_health_check_calls_get_me(monkeypatch: pytest.MonkeyPatch) -> None:
    async def get_me(bot_token: str) -> dict[str, object]:
        assert bot_token == "secret-token"
        return {"id": 1, "username": "northstar_test_bot"}

    monkeypatch.setattr(telegram_client, "get_me", get_me)
    async def get_webhook_info(_: str) -> dict[str, object]:
        return {"url": "https://example.com/telegram"}
    monkeypatch.setattr(telegram_client, "get_webhook_info", get_webhook_info)
    result = await TelegramConnector().health_check(_telegram_context())
    assert result == {"status": "healthy", "username": "northstar_test_bot"}


@pytest.mark.anyio
async def test_telegram_health_check_repairs_webhook_after_transient_delivery_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from northstar_api import config
    from northstar_api.services import telegram_provisioning

    tenant_id = uuid4()
    expected_url = f"https://example.com/api/v1/webhooks/channels/{tenant_id}/telegram/chn_test"
    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: SimpleNamespace(app_api_prefix="/api/v1", telegram_public_base_url="https://example.com"),
    )
    monkeypatch.setattr(telegram_provisioning, "public_base", lambda: "https://example.com")
    context = ChannelConnectionContext(
        tenant_id=tenant_id,
        connection_id=uuid4(),
        provider=ChannelProvider.TELEGRAM,
        configuration={"telegram": {"managed": True, "botId": "1"}},
        credentials={"bot_token": "secret-token", "webhook_secret": "webhook-secret"},
        public_id="chn_test",
    )
    webhook_calls = []

    async def get_me(_: str) -> dict[str, object]:
        return {"id": 1, "username": "northstar_test_bot"}

    async def get_webhook_info(_: str) -> dict[str, object]:
        return {"url": expected_url, "last_error_message": "Temporary network failure"}

    async def set_webhook(token: str, *, url: str, secret_token: str, allowed_updates=None) -> None:
        webhook_calls.append((token, url, secret_token))

    monkeypatch.setattr(telegram_client, "get_me", get_me)
    monkeypatch.setattr(telegram_client, "get_webhook_info", get_webhook_info)
    monkeypatch.setattr(telegram_client, "set_webhook", set_webhook)

    result = await TelegramConnector().health_check(context)

    assert result == {"status": "healthy", "username": "northstar_test_bot"}
    assert webhook_calls == [("secret-token", expected_url, "webhook-secret")]


@pytest.mark.anyio
async def test_telegram_health_check_does_not_report_invalid_token_healthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def get_me(_: str) -> dict[str, object]:
        raise TelegramAPIError("Unauthorized", status_code=401, requires_reconnect=True)

    monkeypatch.setattr(telegram_client, "get_me", get_me)
    result = await TelegramConnector().health_check(_telegram_context())
    assert result == {"status": "auth_required"}


@pytest.mark.anyio
async def test_telegram_client_classifies_auth_and_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = [
        httpx.Response(401, json={"ok": False, "error_code": 401, "description": "Unauthorized"}),
        httpx.Response(
            429,
            json={
                "ok": False,
                "error_code": 429,
                "description": "Too Many Requests",
                "parameters": {"retry_after": 7},
            },
        ),
    ]

    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, url: str, json: object) -> httpx.Response:
            assert "secret-token" in url
            return responses.pop(0)

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    client = TelegramBotClient()

    with pytest.raises(TelegramAPIError) as auth_error:
        await client.get_me("secret-token")
    assert auth_error.value.requires_reconnect is True
    assert auth_error.value.retryable is False

    with pytest.raises(TelegramAPIError) as rate_error:
        await client.send_text("secret-token", chat_id="42", text="hello")
    assert rate_error.value.retryable is True
    assert rate_error.value.retry_after_seconds == 7


@pytest.mark.anyio
async def test_telegram_client_returns_provider_message_id(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, url: str, json: object) -> httpx.Response:
            assert url.endswith("/sendMessage")
            assert json == {"chat_id": "42", "text": "hello"}
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 991}})

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    result = await TelegramBotClient().send_text("secret-token", chat_id="42", text="hello")
    assert result == "991"


@pytest.mark.anyio
async def test_conversation_reply_creates_durable_telegram_delivery_and_preserves_api_reply(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CRM_CREDENTIAL_ENCRYPTION_KEY", "telegram-test-encryption-key")
    monkeypatch.setattr(send_telegram_message, "apply_async", lambda *args, **kwargs: None)

    workspace_response = await client.get("/api/v1/workspace", headers=auth_headers)
    assert workspace_response.status_code == 200, workspace_response.text
    workspace = workspace_response.json()
    tenant_id = UUID(workspace["tenantId"])
    workspace_id = UUID(workspace["id"])
    agent_id = uuid4()
    telegram_conversation_id = uuid4()
    api_conversation_id = uuid4()

    async with SessionFactory() as session:
        session.add(
            Agent(
                id=agent_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                name=f"Telegram test {agent_id.hex[:8]}",
            )
        )
        session.add_all(
            [
                Conversation(
                    id=telegram_conversation_id,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    visitor_id="telegram:-100123456",
                    visitor_name="Telegram user",
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
            "provider": "telegram",
            "name": f"Telegram {agent_id.hex[:8]}",
            "agentId": str(agent_id),
            "configuration": {"agentId": str(agent_id)},
            "credentials": {
                "bot_token": "123456:bot-secret",
                "webhook_secret": "webhook-secret",
            },
        },
    )
    assert connection.status_code == 201, connection.text

    telegram_reply = await client.post(
        f"/api/v1/conversations/{telegram_conversation_id}/messages",
        headers=auth_headers,
        json={"content": "Hello from Northstar"},
    )
    assert telegram_reply.status_code == 201, telegram_reply.text

    api_reply = await client.post(
        f"/api/v1/conversations/{api_conversation_id}/messages",
        headers=auth_headers,
        json={"content": "Local API reply"},
    )
    assert api_reply.status_code == 201, api_reply.text

    async with SessionFactory() as session:
        telegram_message = await session.get(Message, UUID(telegram_reply.json()["id"]))
        api_message = await session.get(Message, UUID(api_reply.json()["id"]))
        assert telegram_message is not None
        assert api_message is not None
        assert telegram_message.finish_reason == "queued"
        assert api_message.finish_reason == "sent"

        deliveries = list(
            await session.scalars(
                select(ChannelOutboundDelivery).where(
                    ChannelOutboundDelivery.tenant_id == tenant_id,
                    ChannelOutboundDelivery.message_id == telegram_message.id,
                )
            )
        )
        assert len(deliveries) == 1
        assert deliveries[0].provider == "telegram"
        assert deliveries[0].recipient_external_id == "-100123456"
        assert deliveries[0].status == "queued"

        api_delivery = await session.scalar(
            select(ChannelOutboundDelivery).where(
                ChannelOutboundDelivery.message_id == api_message.id
            )
        )
        assert api_delivery is None
