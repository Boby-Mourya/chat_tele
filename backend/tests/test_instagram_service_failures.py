from __future__ import annotations

import httpx
import pytest

from northstar_api.services.instagram import InstagramAPIError, InstagramMessagingClient


def test_missing_access_token_requires_reconnect() -> None:
    with pytest.raises(InstagramAPIError) as raised:
        InstagramMessagingClient._headers("   ")
    assert raised.value.requires_reconnect is True


def test_missing_professional_account_id_is_rejected() -> None:
    client = InstagramMessagingClient()
    with pytest.raises(InstagramAPIError):
        client._url("", api_version="v26.0")


@pytest.mark.anyio
async def test_timeout_is_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def request(self, *args: object, **kwargs: object) -> httpx.Response:
            raise httpx.ReadTimeout("timeout")

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    with pytest.raises(InstagramAPIError) as raised:
        await InstagramMessagingClient().get_account("token", account_id="123456")
    assert raised.value.retryable is True


@pytest.mark.anyio
async def test_success_without_provider_message_id_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def request(self, *args: object, **kwargs: object) -> httpx.Response:
            return httpx.Response(200, json={"recipient_id": "1789"})

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    with pytest.raises(InstagramAPIError) as raised:
        await InstagramMessagingClient().send_text(
            "token",
            account_id="123456",
            recipient_id="1789",
            text="hello",
        )
    assert "message ID" in str(raised.value)
