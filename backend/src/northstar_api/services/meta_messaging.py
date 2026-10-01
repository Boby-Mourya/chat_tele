from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from northstar_api.lead_crm.domain import ChannelProvider

META_TEXT_LIMIT = 1000
_META_RETRYABLE_CODES = frozenset({1, 2, 4, 17, 32, 613})


@dataclass(slots=True)
class MetaMessagingAPIError(RuntimeError):
    message: str
    status_code: int | None = None
    provider_code: int | None = None
    retryable: bool = False
    requires_reconnect: bool = False

    def __str__(self) -> str:
        return self.message


def split_meta_text(text: str, limit: int = META_TEXT_LIMIT) -> list[str]:
    value = text.strip()
    if not value:
        return []
    if limit < 1:
        raise ValueError("Meta message text chunk limit must be positive")
    chunks: list[str] = []
    remaining = value
    while len(remaining) > limit:
        window = remaining[:limit]
        split_at = max(window.rfind("\n"), window.rfind(" "))
        if split_at < max(1, limit // 2):
            split_at = limit
        chunk = remaining[:split_at].rstrip()
        if not chunk:
            chunk = remaining[:limit]
            split_at = len(chunk)
        chunks.append(chunk)
        remaining = remaining[split_at:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


def _provider_host(provider: ChannelProvider) -> str:
    if provider == ChannelProvider.FACEBOOK_MESSENGER:
        return "https://graph.facebook.com"
    if provider == ChannelProvider.INSTAGRAM:
        return "https://graph.instagram.com"
    raise MetaMessagingAPIError("Unsupported Meta messaging provider")


class MetaMessagingClient:
    def __init__(self, *, timeout_seconds: float = 10.0) -> None:
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _version(value: str) -> str:
        version = value.strip()
        if not version or len(version) > 24 or not version.startswith("v"):
            raise MetaMessagingAPIError("Meta Graph API version is not configured correctly")
        return version

    async def _request(
        self,
        provider: ChannelProvider,
        *,
        access_token: str,
        api_version: str,
        sender_id: str,
        method: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        token = access_token.strip()
        sender = sender_id.strip()
        if not token:
            raise MetaMessagingAPIError("Meta access token is not configured", requires_reconnect=True)
        if not sender:
            raise MetaMessagingAPIError("Meta sender ID is not configured")
        url = f"{_provider_host(provider)}/{self._version(api_version)}/{sender}/{method}"
        headers = {"Authorization": f"Bearer {token}"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                if method == "messages":
                    response = await client.post(url, headers=headers, json=payload or {})
                else:
                    response = await client.get(url, headers=headers, params=payload or {})
        except httpx.TimeoutException as exc:
            raise MetaMessagingAPIError("Meta messaging request timed out", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise MetaMessagingAPIError("Meta messaging network request failed", retryable=True) from exc

        try:
            decoded = response.json()
            body = decoded if isinstance(decoded, dict) else {}
        except ValueError:
            body = {}
        if response.is_success and not body.get("error"):
            return body

        error = body.get("error") if isinstance(body.get("error"), dict) else {}
        raw_code = error.get("code")
        try:
            provider_code = int(raw_code) if raw_code is not None else None
        except (TypeError, ValueError):
            provider_code = None
        message = str(error.get("message") or "Meta messaging API request failed")[:500]
        reconnect = response.status_code in {401, 403} or provider_code in {10, 190}
        retryable = response.status_code == 429 or response.status_code >= 500 or provider_code in _META_RETRYABLE_CODES
        raise MetaMessagingAPIError(
            message,
            status_code=response.status_code,
            provider_code=provider_code,
            retryable=retryable,
            requires_reconnect=reconnect,
        )

    async def get_identity(
        self,
        provider: ChannelProvider,
        *,
        access_token: str,
        api_version: str,
        sender_id: str,
    ) -> dict[str, Any]:
        fields = "id,name" if provider == ChannelProvider.FACEBOOK_MESSENGER else "id,username"
        return await self._request(
            provider,
            access_token=access_token,
            api_version=api_version,
            sender_id=sender_id,
            method="",
            payload={"fields": fields},
        )

    async def send_text(
        self,
        provider: ChannelProvider,
        *,
        access_token: str,
        api_version: str,
        sender_id: str,
        recipient_id: str,
        text: str,
    ) -> str:
        payload: dict[str, Any] = {
            "recipient": {"id": recipient_id},
            "message": {"text": text},
        }
        if provider == ChannelProvider.FACEBOOK_MESSENGER:
            payload["messaging_type"] = "RESPONSE"
        body = await self._request(
            provider,
            access_token=access_token,
            api_version=api_version,
            sender_id=sender_id,
            method="messages",
            payload=payload,
        )
        message_id = body.get("message_id")
        if not message_id:
            raise MetaMessagingAPIError("Meta accepted the request without returning a message ID")
        return str(message_id)


meta_messaging_client = MetaMessagingClient()
