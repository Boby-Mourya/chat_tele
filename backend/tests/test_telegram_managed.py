from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr

from northstar_api.config import get_settings
from northstar_api.database import SessionFactory
from northstar_api.lead_crm.channel_models import ChannelConnection
from northstar_api.lead_crm.credentials import credential_store
from northstar_api.services.rate_limit import redis_services
from northstar_api.services.telegram import TelegramAPIError, telegram_client
from northstar_api.services.telegram_provisioning import public_base
from northstar_api.telegram_provisioning import TelegramProvisioning

pytestmark = pytest.mark.usefixtures("crm_test_plan")
MANAGER_SECRET = "test-manager-verification-" + "x" * 32


@pytest.fixture
def telegram(monkeypatch):
    monkeypatch.setattr(redis_services, "_memory_windows", {})
    settings = get_settings()
    monkeypatch.setattr(settings, "telegram_manager_bot_token", SecretStr("test-manager-token"))
    monkeypatch.setattr(settings, "telegram_manager_bot_username", "test_manager_bot")
    monkeypatch.setattr(settings, "telegram_manager_webhook_secret", SecretStr(MANAGER_SECRET))
    monkeypatch.setattr(settings, "telegram_public_base_url", "https://telegram.example.com")
    monkeypatch.setenv("CRM_CREDENTIAL_ENCRYPTION_KEY", "test-encryption-key-for-managed-telegram")
    calls = {}
    webhook_urls = {}

    def record_webhook(token, **kwargs):
        webhook_urls[token] = kwargs["url"]

    for method in [
        "get_me",
        "get_managed_bot_token",
        "set_webhook",
        "get_webhook_info",
        "delete_webhook",
        "send_text",
        "answer_callback",
        "allow_managed_bot_students",
    ]:
        calls[method] = AsyncMock()
        monkeypatch.setattr(telegram_client, method, calls[method])
    calls["set_webhook"].side_effect = record_webhook
    calls["get_managed_bot_token"].return_value = "test-managed-token"
    calls["get_me"].return_value = {
        "id": 55501,
        "is_bot": True,
        "first_name": "Actual Name",
        "username": "changed_name_bot",
    }
    calls["get_webhook_info"].side_effect = lambda token: {"url": webhook_urls.get(token, "")}
    return calls


async def agent(client, auth_headers, channel="telegram"):
    response = await client.post(
        "/api/v1/agents",
        headers=auth_headers,
        json={"name": f"Managed {uuid4().hex[:8]}", "deploymentChannel": channel},
    )
    assert response.status_code == 201
    return response.json()["id"]


async def begin(client, auth_headers, agent_id):
    response = await client.post(
        "/api/v1/channels/telegram/connect/start", headers=auth_headers, json={"agentId": agent_id}
    )
    assert response.status_code == 200, response.text
    return response.json()


async def event(client, update_id, **payload):
    return await client.post(
        "/api/v1/webhooks/telegram/manager",
        headers={"X-Telegram-Bot-Api-Secret-Token": MANAGER_SECRET},
        json={"update_id": update_id, **payload},
    )


async def open_manager(client, started, update_id=100, user=500):
    nonce = parse_qs(urlsplit(started["telegramUrl"]).query)["start"][0]
    return await event(
        client,
        update_id,
        message={"text": f"/start {nonce}", "from": {"id": user}, "chat": {"id": user, "type": "private"}},
    )


async def test_full_flow_identity_secrets_idempotency_disconnect_reconnect(client, auth_headers, telegram):
    aid = await agent(client, auth_headers)
    started = await begin(client, auth_headers, aid)
    repeated = await begin(client, auth_headers, aid)
    assert repeated["sessionId"] == started["sessionId"]
    assert repeated["telegramUrl"] == started["telegramUrl"]
    assert aid not in started["telegramUrl"]
    assert (await open_manager(client, started)).status_code == 200
    button = telegram["send_text"].call_args.kwargs["reply_markup"]["inline_keyboard"][0][0]
    assert button["text"] == "Create bot"
    creation = urlsplit(button["url"])
    assert creation.netloc == "t.me"
    assert creation.path.startswith("/newbot/test_manager_bot/")
    assert creation.path.endswith("bot")
    assert len(creation.path.split("/")[-1]) <= 32
    assert parse_qs(creation.query)["name"]
    assert (
        await event(
            client,
            101,
            managed_bot={"user": {"id": 500}, "bot": {"id": 55501, "username": "changed_name_bot"}},
        )
    ).status_code == 200
    callback = telegram["send_text"].call_args.kwargs["reply_markup"]["inline_keyboard"][0][0][
        "callback_data"
    ]
    assert len(callback.encode()) <= 64
    # Different Telegram account cannot confirm this workspace's session.
    webhook_call_count = telegram["set_webhook"].await_count
    await event(client, 102, callback_query={"id": "wrong", "from": {"id": 501}, "data": callback})
    assert telegram["set_webhook"].await_count == webhook_call_count
    assert (
        await event(client, 103, callback_query={"id": "right", "from": {"id": 500}, "data": callback})
    ).status_code == 200
    await event(client, 103, callback_query={"id": "right", "from": {"id": 500}, "data": callback})
    assert telegram["set_webhook"].await_count == webhook_call_count + 1
    status = (
        await client.get(
            f"/api/v1/channels/telegram/provisioning/{started['sessionId']}", headers=auth_headers
        )
    ).json()
    assert status["status"] == "connected"
    assert status["bot"]["studentUrl"] == "https://t.me/changed_name_bot"
    assert status["bot"]["botName"] == "Actual Name"
    assert "test-managed-token" not in str(status) and "webhook_secret" not in str(status)
    cid = status["connectionId"]
    async with SessionFactory() as session:
        connection = await session.get(ChannelConnection, UUID(cid))
        credentials = credential_store.decrypt(connection.credentials_encrypted)
        assert credentials["bot_token"] == "test-managed-token"  # noqa: S105
        assert len(credentials["webhook_secret"]) >= 32
        assert telegram["set_webhook"].call_args.kwargs["secret_token"] == credentials["webhook_secret"]
        assert telegram["set_webhook"].call_args.kwargs["url"].endswith(f"/telegram/{connection.public_id}")
        assert connection.status == "healthy" and connection.last_event_at is None
    for _ in range(2):
        assert (
            await client.delete(f"/api/v1/channels/connections/{cid}", headers=auth_headers)
        ).status_code == 204
    telegram["delete_webhook"].assert_awaited_once_with("test-managed-token")
    async with SessionFactory() as session:
        connection = await session.get(ChannelConnection, UUID(cid))
        assert connection.credentials_encrypted is None
        assert connection.configuration_json["telegram"]["botId"] == "55501"
        denied = await client.post(
            f"/api/v1/webhooks/channels/{connection.tenant_id}/telegram/{connection.public_id}",
            json={"update_id": 22},
        )
        assert denied.status_code == 404
    # Telegram keeps historical delivery errors even after setWebhook succeeds.
    webhook_info = telegram["get_webhook_info"].side_effect
    telegram["get_webhook_info"].side_effect = lambda token: {
        **webhook_info(token),
        "last_error_date": 1,
        "last_error_message": "Previous webhook was unavailable",
    }
    reconnect = await begin(client, auth_headers, aid)
    assert reconnect["status"] == "connected" and reconnect["connectionId"] == cid
    assert "telegramUrl" not in reconnect
    async with SessionFactory() as session:
        value = await session.get(TelegramProvisioning, UUID(started["sessionId"]))
        assert value.bot_id == "55501"


async def test_start_authorization_expiry_and_webhook_auth(client, auth_headers, telegram):
    aid = await agent(client, auth_headers)
    assert (
        await client.post("/api/v1/channels/telegram/connect/start", json={"agentId": aid})
    ).status_code == 401
    assert (
        await client.post(
            "/api/v1/channels/telegram/connect/start", headers=auth_headers, json={"agentId": str(uuid4())}
        )
    ).status_code == 404
    website = await agent(client, auth_headers, "website")
    assert (
        await client.post(
            "/api/v1/channels/telegram/connect/start", headers=auth_headers, json={"agentId": website}
        )
    ).status_code == 409
    started = await begin(client, auth_headers, aid)
    assert (
        await client.post("/api/v1/webhooks/telegram/manager", json={"update_id": 200})
    ).status_code == 401
    await event(
        client, 201, message={"text": "/start invalid", "from": {"id": 500}, "chat": {"type": "private"}}
    )
    telegram["send_text"].assert_not_called()
    async with SessionFactory() as session:
        value = await session.get(TelegramProvisioning, UUID(started["sessionId"]))
        value.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    await open_manager(client, started, 202)
    telegram["send_text"].assert_not_called()
    status = await client.get(
        f"/api/v1/channels/telegram/provisioning/{started['sessionId']}", headers=auth_headers
    )
    assert status.json()["status"] == "expired"


@pytest.mark.parametrize("method", ["get_webhook_info", "set_webhook"])
async def test_manager_webhook_provider_failure_returns_service_unavailable(
    client, auth_headers, telegram, method
):
    aid = await agent(client, auth_headers)
    if method == "get_webhook_info":
        telegram[method].side_effect = TelegramAPIError("private provider detail", status_code=500)
    else:
        telegram["get_webhook_info"].side_effect = lambda _: {"url": "https://old.example.com"}
        telegram[method].side_effect = TelegramAPIError("private provider detail", status_code=500)

    response = await client.post(
        "/api/v1/channels/telegram/connect/start", headers=auth_headers, json={"agentId": aid}
    )

    assert response.status_code == 503
    assert "temporarily unavailable" in response.json()["error"]["message"]
    assert "private provider detail" not in response.text


async def test_partial_webhook_failure_retains_state_for_retry(client, auth_headers, telegram):
    telegram["get_me"].return_value["id"] = 55502
    aid = await agent(client, auth_headers)
    started = await begin(client, auth_headers, aid)
    await open_manager(client, started, 300)
    await event(
        client, 301, managed_bot={"user": {"id": 500}, "bot": {"id": 55502, "username": "another_bot"}}
    )
    callback = telegram["send_text"].call_args.kwargs["reply_markup"]["inline_keyboard"][0][0][
        "callback_data"
    ]
    telegram["get_webhook_info"].side_effect = lambda _: {"url": "https://wrong.example.com"}
    await event(client, 302, callback_query={"id": "partial", "from": {"id": 500}, "data": callback})
    status = (
        await client.get(
            f"/api/v1/channels/telegram/provisioning/{started['sessionId']}", headers=auth_headers
        )
    ).json()
    assert status["status"] == "failed"
    assert "token" not in str(status)
    telegram["get_webhook_info"].side_effect = lambda _: {
        "url": telegram["set_webhook"].call_args.kwargs["url"]
    }
    assert (await begin(client, auth_headers, aid))["status"] == "connected"


@pytest.mark.parametrize(
    "url",
    [
        "http://public.example.com",
        "https://localhost",
        "https://127.0.0.1",
        "https://user:pass@example.com",
        "https://example.com/#fragment",
        "https://example.com/?query=1",
    ],
)
def test_public_url_rejects_unsafe_configuration(url, monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(get_settings(), "telegram_public_base_url", url)
    with pytest.raises(HTTPException):
        public_base()


async def test_current_public_base_selects_https_tunnel_for_web_port(monkeypatch):
    from northstar_api.services import telegram_provisioning as service

    settings = get_settings()
    monkeypatch.setattr(settings, "telegram_ngrok_api_url", "http://ngrok.test/api/tunnels")
    monkeypatch.setattr(settings, "telegram_ngrok_tunnel_port", 3100)

    class Response:
        def raise_for_status(self):
            pass

        @staticmethod
        def json():
            return {
                "tunnels": [
                    {"proto": "http", "public_url": "http://wrong.example", "config": {"addr": "localhost:3100"}},
                    {"proto": "https", "public_url": "https://wrong.example", "config": {"addr": "localhost:8000"}},
                    {"proto": "https", "public_url": "https://active.example", "config": {"addr": "localhost:3100"}},
                ]
            }

    class Client:
        def __init__(self, *, timeout):
            assert timeout == 2.0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def get(self, url):
            assert url == "http://ngrok.test/api/tunnels"
            return Response()

    monkeypatch.setattr(service.httpx, "AsyncClient", Client)
    assert await service.current_public_base() == "https://active.example"


@pytest.mark.parametrize("method,code", [("get_managed_bot_token", 403), ("get_managed_bot_token", 429), ("get_me", 401), ("set_webhook", 500), ("get_webhook_info", 500)])
async def test_provider_failures_never_report_connected(client, auth_headers, telegram, method, code):
    number = uuid4().int % (2**40)
    telegram["get_me"].return_value["id"] = number
    started = await begin(client, auth_headers, await agent(client, auth_headers))
    await open_manager(client, started, number)
    await event(client, number + 1, managed_bot={"user": {"id": 500}, "bot": {"id": number}})
    callback = telegram["send_text"].call_args.kwargs["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
    telegram[method].side_effect = TelegramAPIError("test-provider-error", status_code=code, retryable=code >= 429)
    assert (await event(client, number + 2, callback_query={"id": "error", "from": {"id": 500}, "data": callback})).status_code == 200
    status = (await client.get(f"/api/v1/channels/telegram/provisioning/{started['sessionId']}", headers=auth_headers)).json()
    assert status["status"] == "failed"
    assert "test-provider-error" not in str(status)


async def test_scope_and_permission_rechecked_at_completion(client, auth_headers, telegram, monkeypatch):
    from northstar_api.services import telegram_provisioning as service
    from northstar_api.services.entitlements import EntitlementError
    aid = await agent(client, auth_headers)
    wrong_workspace = {**auth_headers, "X-Workspace-ID": str(uuid4())}
    assert (await client.post("/api/v1/channels/telegram/connect/start", headers=wrong_workspace, json={"agentId": aid})).status_code == 403
    started = await begin(client, auth_headers, aid)
    await open_manager(client, started, 600)
    await event(client, 601, managed_bot={"user": {"id": 500}, "bot": {"id": 55509}})
    callback = telegram["send_text"].call_args.kwargs["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
    async def denied(*args, **kwargs):
        raise EntitlementError("Plan no longer permits Telegram", status_code=403, code="channel_not_available")
    monkeypatch.setattr(service, "require_channel", denied)
    await event(client, 602, callback_query={"id": "denied", "from": {"id": 500}, "data": callback})
    telegram["get_managed_bot_token"].assert_not_called()
    status = (await client.get(f"/api/v1/channels/telegram/provisioning/{started['sessionId']}", headers=auth_headers)).json()
    assert status["status"] == "failed"
    assert (await client.post("/api/v1/channels/telegram/connect/start", headers=auth_headers, json={"agentId": aid})).status_code == 403


async def test_managed_metadata_cannot_be_forged_through_legacy_api(client, auth_headers, telegram):
    response = await client.post("/api/v1/channels/connections", headers=auth_headers, json={
        "provider": "telegram", "name": "Forged managed bot", "configuration": {"telegram": {"managed": True, "botId": "55501"}}})
    assert response.status_code == 422


async def test_legacy_disconnect_keeps_credentials_when_provider_is_temporarily_unavailable(client, auth_headers, telegram):
    created = await client.post("/api/v1/channels/connections", headers=auth_headers, json={
        "provider": "telegram", "name": "Legacy retry " + uuid4().hex, "credentials": {"bot_token": "fake-legacy", "webhook_secret": "fake-secret"}})
    assert created.status_code == 201
    cid = created.json()["id"]
    telegram["delete_webhook"].side_effect = TelegramAPIError("Unavailable", status_code=500, retryable=True)
    assert (await client.delete(f"/api/v1/channels/connections/{cid}", headers=auth_headers)).status_code == 503
    async with SessionFactory() as session:
        connection = await session.get(ChannelConnection, UUID(cid))
        assert connection.credentials_encrypted is not None
        assert connection.status != "disabled"
    telegram["delete_webhook"].side_effect = None
    assert (await client.delete(f"/api/v1/channels/connections/{cid}", headers=auth_headers)).status_code == 204


async def test_client_managed_token_and_boolean_contracts(monkeypatch):
    from northstar_api.services.telegram import TelegramBotClient
    client = TelegramBotClient()
    request = AsyncMock(return_value="synthetic-managed-credential")
    monkeypatch.setattr(client, "_request", request)
    assert await client.get_managed_bot_token("synthetic-manager", "123") == "synthetic-managed-credential"
    request.assert_awaited_with("synthetic-manager", "getManagedBotToken", {"user_id": 123})
    request.return_value = True
    await client.set_webhook("synthetic", url="https://api.example.com/hook", secret_token="test-only-secret")  # noqa: S106
    assert request.call_args.args[2]["allowed_updates"] == ["message", "edited_message", "business_message"]
    await client.allow_managed_bot_students("synthetic-manager", "123")
    assert request.call_args.args[2] == {"user_id": 123, "is_access_restricted": False}
    request.return_value = False
    with pytest.raises(TelegramAPIError):
        await client.delete_webhook("synthetic")
    with pytest.raises(TelegramAPIError):
        await client.get_me("synthetic")
    with pytest.raises(TelegramAPIError):
        await client.get_webhook_info("synthetic")


async def test_multiple_accounts_are_independent_and_workspace_scoped(client, auth_headers, telegram):
    aid = await agent(client, auth_headers)
    connections = []
    for offset in range(2):
        account_id = str(uuid4())
        body = {"agentId": aid, "accountId": account_id}
        response = await client.post("/api/v1/channels/telegram/connect/start", headers=auth_headers, json=body)
        assert response.status_code == 200
        started = response.json()
        assert started["sessionId"] == account_id
        repeated = await client.post("/api/v1/channels/telegram/connect/start", headers=auth_headers, json=body)
        assert repeated.json()["sessionId"] == account_id
        number = 700000 + offset * 10
        owner = 800 + offset
        telegram["get_me"].return_value = {"id": number, "is_bot": True, "first_name": "Independent bot", "username": f"independent_{offset}_bot"}
        await open_manager(client, started, number, user=owner)
        await event(client, number + 1, managed_bot={"user": {"id": owner}, "bot": {"id": number}})
        callback = telegram["send_text"].call_args.kwargs["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
        await event(client, number + 2, callback_query={"id": "multi", "from": {"id": owner}, "data": callback})
        status = (await client.get(f"/api/v1/channels/telegram/provisioning/{account_id}", headers=auth_headers)).json()
        assert status["status"] == "connected"
        connections.append(status["connectionId"])
    assert connections[0] != connections[1]
    assert (await client.delete(f"/api/v1/channels/connections/{connections[0]}", headers=auth_headers)).status_code == 204
    async with SessionFactory() as session:
        first = await session.get(ChannelConnection, UUID(connections[0]))
        second = await session.get(ChannelConnection, UUID(connections[1]))
        assert first.status == "disabled" and first.credentials_encrypted is None
        assert second.status == "healthy" and second.credentials_encrypted
    another_agent = await agent(client, auth_headers)
    for key, value in [("accountId", account_id), ("connectionId", connections[1])]:
        denied = await client.post("/api/v1/channels/telegram/connect/start", headers=auth_headers, json={"agentId": another_agent, key: value})
        assert denied.status_code == 404
    telegram["get_me"].return_value["id"] = 700000
    reconnect = await client.post("/api/v1/channels/telegram/connect/start", headers=auth_headers, json={"agentId": aid, "connectionId": connections[0]})
    assert reconnect.status_code == 200
    assert reconnect.json()["connectionId"] == connections[0]
    assert reconnect.json()["status"] == "connected"


async def test_two_agents_can_provision_independently(client, auth_headers, telegram):
    agent_ids = [await agent(client, auth_headers), await agent(client, auth_headers)]
    started = [await begin(client, auth_headers, agent_id) for agent_id in agent_ids]
    assert started[0]["sessionId"] != started[1]["sessionId"]

    owners = [901, 902]
    bot_ids = [810001, 810002]
    callbacks = []
    for offset, (session, owner, bot_id) in enumerate(zip(started, owners, bot_ids, strict=True)):
        await open_manager(client, session, 900 + offset * 10, user=owner)
        await event(
            client,
            901 + offset * 10,
            managed_bot={"user": {"id": owner}, "bot": {"id": bot_id, "username": f"agent_{offset}_bot"}},
        )
        callbacks.append(telegram["send_text"].call_args.kwargs["reply_markup"]["inline_keyboard"][0][0]["callback_data"])

    for offset, (_session, owner, bot_id, callback) in enumerate(
        zip(started, owners, bot_ids, callbacks, strict=True)
    ):
        telegram["get_me"].return_value = {
            "id": bot_id,
            "is_bot": True,
            "first_name": f"Agent {offset}",
            "username": f"agent_{offset}_bot",
        }
        await event(
            client,
            902 + offset * 10,
            callback_query={"id": f"agent-{offset}", "from": {"id": owner}, "data": callback},
        )

    for session, agent_id, bot_id in zip(started, agent_ids, bot_ids, strict=True):
        status = (
            await client.get(
                f"/api/v1/channels/telegram/provisioning/{session['sessionId']}", headers=auth_headers
            )
        ).json()
        assert status["status"] == "connected"
        assert status["bot"]["botId"] == str(bot_id)
        async with SessionFactory() as db_session:
            connection = await db_session.get(ChannelConnection, UUID(status["connectionId"]))
            assert connection.configuration_json["agentId"] == agent_id
