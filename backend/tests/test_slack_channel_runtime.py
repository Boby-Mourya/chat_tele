from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from northstar_api.database import SessionFactory
from northstar_api.lead_crm.channel_models import ChannelOutboundDelivery
from northstar_api.lead_crm.channels import ChannelConnectionContext, channel_registry
from northstar_api.lead_crm.domain import ChannelProvider
from northstar_api.lead_crm.slack_channel import SlackConnector
from northstar_api.models import Agent, Channel, Conversation, Message
from northstar_api.routers.conversations import _slack_delivery_target
from northstar_api.services.slack import (
    SLACK_TEXT_LIMIT,
    SlackAPIError,
    SlackWebClient,
    decode_slack_target,
    encode_slack_target,
    slack_client,
    split_slack_text,
)
from northstar_api.workers.slack_tasks import send_slack_message, slack_thread_lock_key


def _context() -> ChannelConnectionContext:
    return ChannelConnectionContext(
        tenant_id=uuid4(),
        connection_id=uuid4(),
        provider=ChannelProvider.SLACK,
        configuration={"agentId": str(uuid4())},
        credentials={"bot_token": "xoxb-test", "signing_secret": "signing-secret"},
    )


def _signed_headers(body: bytes, timestamp: int, secret: str = "signing-secret") -> dict[str, str]:
    base = f"v0:{timestamp}:".encode() + body
    signature = "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
    return {
        "x-slack-request-timestamp": str(timestamp),
        "x-slack-signature": signature,
    }


def _conversation(visitor_id: str, *, channel: Channel = Channel.SLACK) -> Conversation:
    return Conversation(
        tenant_id=uuid4(),
        workspace_id=uuid4(),
        agent_id=uuid4(),
        visitor_id=visitor_id,
        visitor_name="Slack user",
        channel=channel,
    )


def test_slack_runtime_replaces_only_the_legacy_generic_connector() -> None:
    assert isinstance(channel_registry.get(ChannelProvider.SLACK), SlackConnector)
    assert channel_registry.get(ChannelProvider.API).provider == ChannelProvider.API
    assert channel_registry.get(ChannelProvider.WIDGET).provider == ChannelProvider.WIDGET
    assert channel_registry.get(ChannelProvider.CUSTOM).provider == ChannelProvider.CUSTOM


@pytest.mark.anyio
async def test_slack_signature_verification_and_replay_protection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 1_789_000_000
    monkeypatch.setattr("northstar_api.lead_crm.slack_channel.time.time", lambda: now)
    body = b'{"type":"event_callback"}'
    connector = SlackConnector()

    assert await connector.verify(
        _context(),
        headers=_signed_headers(body, now),
        body=body,
    )
    assert not await connector.verify(
        _context(),
        headers=_signed_headers(body, now - 301),
        body=body,
    )
    assert not await connector.verify(
        _context(),
        headers={**_signed_headers(body, now), "x-slack-signature": "v0=bad"},
        body=body,
    )


@pytest.mark.anyio
async def test_slack_normalizes_threaded_messages_and_ignores_bot_messages() -> None:
    connector = SlackConnector()
    payload = {
        "type": "event_callback",
        "team_id": "T123",
        "api_app_id": "A123",
        "event_id": "Ev123",
        "event": {
            "type": "message",
            "user": "U123",
            "channel": "C123ABC",
            "ts": "1789000000.123456",
            "thread_ts": "1788999999.111111",
            "text": "Hello Northstar",
            "client_msg_id": "msg-123",
        },
    }
    values = await connector.normalize(
        _context(),
        payload=payload,
        correlation_id="corr-1",
        received_at=datetime.now(UTC),
    )
    assert len(values) == 1
    event = values[0]
    assert event.external_event_id == "Ev123"
    assert event.sender.external_id == "U123"
    assert event.message is not None and event.message.text == "Hello Northstar"
    assert event.conversation_reference == "C123ABC|1788999999.111111"
    assert event.metadata["channelId"] == "C123ABC"
    assert event.metadata["threadTs"] == "1788999999.111111"

    bot_payload = {**payload, "event": {**payload["event"], "bot_id": "B123"}}
    assert (
        await connector.normalize(
            _context(),
            payload=bot_payload,
            correlation_id="corr-2",
            received_at=datetime.now(UTC),
        )
        == []
    )


def test_slack_target_codec_and_conversation_routing_are_exact() -> None:
    target = encode_slack_target("C123ABC", "1789000000.123456")
    assert target == "C123ABC|1789000000.123456"
    assert decode_slack_target(target) == ("C123ABC", "1789000000.123456")
    assert decode_slack_target("C123ABC") is None
    assert decode_slack_target("X123|1789000000.123456") is None
    assert _slack_delivery_target(_conversation(f"slack:{target}")) == target
    assert _slack_delivery_target(_conversation(f"api:{target}", channel=Channel.API)) is None


def test_slack_text_splitter_preserves_content_and_limit() -> None:
    source = ("northstar " * 1000).strip()
    chunks = split_slack_text(source)
    assert len(chunks) >= 2
    assert all(1 <= len(chunk) <= SLACK_TEXT_LIMIT for chunk in chunks)
    assert " ".join(" ".join(chunks).split()) == " ".join(source.split())
    assert split_slack_text("   ") == []


def test_slack_thread_lock_is_connection_and_target_scoped() -> None:
    connection_id = uuid4()
    target = "C123|1789000000.123456"
    first = slack_thread_lock_key(connection_id, target)
    assert first == slack_thread_lock_key(connection_id, target)
    assert first != slack_thread_lock_key(connection_id, "C124|1789000000.123456")
    assert first != slack_thread_lock_key(uuid4(), target)


@pytest.mark.anyio
async def test_slack_health_check_uses_auth_test(monkeypatch: pytest.MonkeyPatch) -> None:
    async def auth_test(bot_token: str) -> dict[str, object]:
        assert bot_token == "xoxb-test"
        return {"ok": True, "team": "Northstar", "user": "northstar-bot"}

    monkeypatch.setattr(slack_client, "auth_test", auth_test)
    result = await SlackConnector().health_check(_context())
    assert result == {"status": "healthy", "team": "Northstar", "user": "northstar-bot"}


@pytest.mark.anyio
async def test_slack_client_uses_chat_post_message_thread_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
            return httpx.Response(200, json={"ok": True, "channel": "C123", "ts": "1789000001.222222"})

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    result = await SlackWebClient().post_message(
        "xoxb-test",
        channel_id="C123",
        thread_ts="1789000000.111111",
        text="hello",
    )
    assert result == "1789000001.222222"
    assert captured["method"] == "POST"
    assert captured["url"] == "https://slack.com/api/chat.postMessage"
    assert captured["headers"] == {
        "Authorization": "Bearer xoxb-test",
        "Content-Type": "application/json; charset=utf-8",
    }
    assert captured["json"] == {
        "channel": "C123",
        "text": "hello",
        "thread_ts": "1789000000.111111",
    }


@pytest.mark.anyio
async def test_slack_client_classifies_auth_and_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = [
        httpx.Response(200, json={"ok": False, "error": "invalid_auth"}),
        httpx.Response(
            429,
            headers={"Retry-After": "7"},
            json={"ok": False, "error": "ratelimited"},
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
    client = SlackWebClient()
    with pytest.raises(SlackAPIError) as auth_error:
        await client.auth_test("bad")
    assert auth_error.value.requires_reconnect is True
    assert auth_error.value.retryable is False

    with pytest.raises(SlackAPIError) as rate_error:
        await client.post_message("xoxb-test", channel_id="C123", text="hello")
    assert rate_error.value.retryable is True
    assert rate_error.value.retry_after_seconds == 7


@pytest.mark.anyio
async def test_slack_url_verification_returns_signed_challenge(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CRM_CREDENTIAL_ENCRYPTION_KEY", "slack-test-encryption-key")
    workspace_response = await client.get("/api/v1/workspace", headers=auth_headers)
    assert workspace_response.status_code == 200, workspace_response.text
    workspace = workspace_response.json()
    tenant_id = UUID(workspace["tenantId"])
    workspace_id = UUID(workspace["id"])
    agent_id = uuid4()
    async with SessionFactory() as session:
        session.add(
            Agent(
                id=agent_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                name=f"Slack webhook {agent_id.hex[:8]}",
            )
        )
        await session.commit()

    connection = await client.post(
        "/api/v1/channels/connections",
        headers=auth_headers,
        json={
            "provider": "slack",
            "name": f"Slack {agent_id.hex[:8]}",
            "agentId": str(agent_id),
            "configuration": {"agentId": str(agent_id)},
            "credentials": {"bot_token": "xoxb-test", "signing_secret": "signing-secret"},
        },
    )
    assert connection.status_code == 201, connection.text
    connection_body = connection.json()
    public_id = connection_body["public_id"]
    assert connection_body["webhook_path"] == (
        f"/api/v1/webhooks/channels/{tenant_id}/slack/{public_id}"
    )
    challenge = "slack-challenge-123"
    body = json.dumps(
        {"type": "url_verification", "challenge": challenge, "token": "deprecated"},
        separators=(",", ":"),
    ).encode()
    timestamp = int(time.time())
    response = await client.post(
        f"/api/v1/webhooks/channels/{tenant_id}/slack/{public_id}",
        content=body,
        headers={"content-type": "application/json", **_signed_headers(body, timestamp)},
    )
    assert response.status_code == 200, response.text
    assert response.text == challenge


@pytest.mark.anyio
async def test_conversation_reply_creates_durable_slack_delivery_and_preserves_api_reply(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CRM_CREDENTIAL_ENCRYPTION_KEY", "slack-test-encryption-key")
    monkeypatch.setattr(send_slack_message, "apply_async", lambda *args, **kwargs: None)

    workspace_response = await client.get("/api/v1/workspace", headers=auth_headers)
    assert workspace_response.status_code == 200, workspace_response.text
    workspace = workspace_response.json()
    tenant_id = UUID(workspace["tenantId"])
    workspace_id = UUID(workspace["id"])
    agent_id = uuid4()
    slack_conversation_id = uuid4()
    api_conversation_id = uuid4()
    target = "C123ABC|1789000000.123456"

    async with SessionFactory() as session:
        session.add(
            Agent(
                id=agent_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                name=f"Slack reply {agent_id.hex[:8]}",
            )
        )
        session.add_all(
            [
                Conversation(
                    id=slack_conversation_id,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    visitor_id=f"slack:{target}",
                    visitor_name="Slack user",
                    channel=Channel.SLACK,
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
            "provider": "slack",
            "name": f"Slack reply {agent_id.hex[:8]}",
            "agentId": str(agent_id),
            "configuration": {"agentId": str(agent_id)},
            "credentials": {"bot_token": "xoxb-test", "signing_secret": "signing-secret"},
        },
    )
    assert connection.status_code == 201, connection.text

    slack_reply = await client.post(
        f"/api/v1/conversations/{slack_conversation_id}/messages",
        headers=auth_headers,
        json={"content": "Hello from Northstar"},
    )
    assert slack_reply.status_code == 201, slack_reply.text

    api_reply = await client.post(
        f"/api/v1/conversations/{api_conversation_id}/messages",
        headers=auth_headers,
        json={"content": "Local API reply"},
    )
    assert api_reply.status_code == 201, api_reply.text

    async with SessionFactory() as session:
        slack_message = await session.get(Message, UUID(slack_reply.json()["id"]))
        api_message = await session.get(Message, UUID(api_reply.json()["id"]))
        assert slack_message is not None
        assert api_message is not None
        assert slack_message.finish_reason == "queued"
        assert api_message.finish_reason == "sent"

        deliveries = list(
            await session.scalars(
                select(ChannelOutboundDelivery).where(
                    ChannelOutboundDelivery.tenant_id == tenant_id,
                    ChannelOutboundDelivery.message_id == slack_message.id,
                )
            )
        )
        assert len(deliveries) == 1
        assert deliveries[0].provider == "slack"
        assert deliveries[0].recipient_external_id == target
        assert deliveries[0].status == "queued"

        api_delivery = await session.scalar(
            select(ChannelOutboundDelivery).where(
                ChannelOutboundDelivery.message_id == api_message.id
            )
        )
        assert api_delivery is None
