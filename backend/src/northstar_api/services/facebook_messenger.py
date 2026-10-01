from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

MESSENGER_API_BASE = "https://graph.facebook.com"
MESSENGER_DEFAULT_API_VERSION = "v26.0"
MESSENGER_TEXT_LIMIT = 2000


@dataclass(slots=True)
class MessengerAPIError(RuntimeError):
    message: str
    status_code: int | None = None
    provider_code: int | None = None
    retryable: bool = False
    requires_reconnect: bool = False
    retry_after_seconds: int | None = None

    def __str__(self) -> str:
        return self.message


def normalize_messenger_api_version(value: object) -> str:
    version = str(value or MESSENGER_DEFAULT_API_VERSION).strip().lower()
    if not version.startswith("v"):
        version = f"v{version}"
    pieces = version[1:].split(".", 1)
    if len(pieces) != 2 or not all(piece.isdigit() for piece in pieces):
        raise MessengerAPIError("Messenger API version is invalid")
    return version


def split_messenger_text(text: str, limit: int = MESSENGER_TEXT_LIMIT) -> list[str]:
    value = text.strip()
    if not value:
        return []
    if limit < 1:
        raise ValueError("Messenger text chunk limit must be positive")
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


class MessengerMessagingClient:
    def __init__(self, *, timeout_seconds: float = 10.0, api_base: str = MESSENGER_API_BASE) -> None:
        self.timeout_seconds = timeout_seconds
        self.api_base = api_base.rstrip("/")

    def _url(self, page_id: str, *, api_version: object, suffix: str = "") -> str:
        normalized_page = page_id.strip()
        if not normalized_page:
            raise MessengerAPIError("Facebook Page ID is not configured")
        version = normalize_messenger_api_version(api_version)
        return f"{self.api_base}/{version}/{normalized_page}{suffix}"

    @staticmethod
    def _headers(page_access_token: str) -> dict[str, str]:
        token = page_access_token.strip()
        if not token:
            raise MessengerAPIError(
                "Facebook Page access token is not configured",
                requires_reconnect=True,
            )
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _retry_after(response: httpx.Response) -> int | None:
        value = response.headers.get("retry-after")
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _error_from_response(response: httpx.Response, body: dict[str, Any]) -> MessengerAPIError:
        error = body.get("error") if isinstance(body.get("error"), dict) else {}
        raw_code = error.get("code")
        try:
            provider_code = int(raw_code) if raw_code is not None else None
        except (TypeError, ValueError):
            provider_code = None
        status_code = response.status_code
        requires_reconnect = status_code in {401, 403} or provider_code in {10, 190}
        retryable = status_code == 429 or status_code >= 500 or provider_code in {1, 2, 4, 17, 32, 613}
        message = str(error.get("message") or "Messenger API request failed")[:500]
        return MessengerAPIError(
            message,
            status_code=status_code,
            provider_code=provider_code,
            retryable=retryable,
            requires_reconnect=requires_reconnect,
            retry_after_seconds=MessengerMessagingClient._retry_after(response),
        )

    async def _request(
        self,
        method: str,
        url: str,
        *,
        page_access_token: str,
        json: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.request(
                    method,
                    url,
                    headers=self._headers(page_access_token),
                    json=json,
                    params=params,
                )
        except httpx.TimeoutException as exc:
            raise MessengerAPIError("Messenger request timed out", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise MessengerAPIError("Messenger network request failed", retryable=True) from exc

        try:
            decoded = response.json()
            body = decoded if isinstance(decoded, dict) else {}
        except ValueError:
            body = {}
        if response.is_success and "error" not in body:
            return body
        raise self._error_from_response(response, body)

    async def get_page(
        self,
        page_access_token: str,
        *,
        page_id: str,
        api_version: object = MESSENGER_DEFAULT_API_VERSION,
    ) -> dict[str, Any]:
        return await self._request(
            "GET",
            self._url(page_id, api_version=api_version),
            page_access_token=page_access_token,
            params={"fields": "id,name"},
        )

    async def send_text(
        self,
        page_access_token: str,
        *,
        page_id: str,
        recipient_id: str,
        text: str,
        api_version: object = MESSENGER_DEFAULT_API_VERSION,
    ) -> str:
        recipient = recipient_id.strip()
        if not recipient:
            raise MessengerAPIError("Messenger recipient PSID is unavailable")
        message = text.strip()
        if not message:
            raise MessengerAPIError("Messenger message text is empty")
        body = await self._request(
            "POST",
            self._url(page_id, api_version=api_version, suffix="/messages"),
            page_access_token=page_access_token,
            json={
                "recipient": {"id": recipient},
                "messaging_type": "RESPONSE",
                "message": {"text": message},
            },
        )
        message_id = body.get("message_id")
        if not message_id:
            raise MessengerAPIError("Messenger accepted the request without returning a message ID")
        return str(message_id)


messenger_client = MessengerMessagingClient()
