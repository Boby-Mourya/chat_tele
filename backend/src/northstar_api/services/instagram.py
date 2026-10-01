from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

INSTAGRAM_API_BASE = "https://graph.instagram.com"
INSTAGRAM_DEFAULT_API_VERSION = "v26.0"
INSTAGRAM_TEXT_LIMIT = 1000


@dataclass(slots=True)
class InstagramAPIError(RuntimeError):
    message: str
    status_code: int | None = None
    provider_code: int | None = None
    retryable: bool = False
    requires_reconnect: bool = False
    retry_after_seconds: int | None = None

    def __str__(self) -> str:
        return self.message


def normalize_instagram_api_version(value: object) -> str:
    version = str(value or INSTAGRAM_DEFAULT_API_VERSION).strip().lower()
    if not version.startswith("v"):
        version = f"v{version}"
    pieces = version[1:].split(".", 1)
    if len(pieces) != 2 or not all(piece.isdigit() for piece in pieces):
        raise InstagramAPIError("Instagram API version is invalid")
    return version


def split_instagram_text(text: str, limit: int = INSTAGRAM_TEXT_LIMIT) -> list[str]:
    value = text.strip()
    if not value:
        return []
    if limit < 1:
        raise ValueError("Instagram text chunk limit must be positive")
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


class InstagramMessagingClient:
    def __init__(self, *, timeout_seconds: float = 10.0, api_base: str = INSTAGRAM_API_BASE) -> None:
        self.timeout_seconds = timeout_seconds
        self.api_base = api_base.rstrip("/")

    def _url(self, account_id: str, *, api_version: object, suffix: str = "") -> str:
        normalized_account = account_id.strip()
        if not normalized_account:
            raise InstagramAPIError("Instagram professional account ID is not configured")
        version = normalize_instagram_api_version(api_version)
        return f"{self.api_base}/{version}/{normalized_account}{suffix}"

    @staticmethod
    def _headers(access_token: str) -> dict[str, str]:
        token = access_token.strip()
        if not token:
            raise InstagramAPIError(
                "Instagram access token is not configured",
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
    def _error_from_response(response: httpx.Response, body: dict[str, Any]) -> InstagramAPIError:
        error = body.get("error") if isinstance(body.get("error"), dict) else {}
        raw_code = error.get("code")
        try:
            provider_code = int(raw_code) if raw_code is not None else None
        except (TypeError, ValueError):
            provider_code = None
        status_code = response.status_code
        requires_reconnect = status_code in {401, 403} or provider_code in {10, 190}
        retryable = status_code == 429 or status_code >= 500 or provider_code in {1, 2, 4, 17, 32, 613}
        message = str(error.get("message") or "Instagram API request failed")[:500]
        return InstagramAPIError(
            message,
            status_code=status_code,
            provider_code=provider_code,
            retryable=retryable,
            requires_reconnect=requires_reconnect,
            retry_after_seconds=InstagramMessagingClient._retry_after(response),
        )

    async def _request(
        self,
        method: str,
        url: str,
        *,
        access_token: str,
        json: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.request(
                    method,
                    url,
                    headers=self._headers(access_token),
                    json=json,
                    params=params,
                )
        except httpx.TimeoutException as exc:
            raise InstagramAPIError("Instagram request timed out", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise InstagramAPIError("Instagram network request failed", retryable=True) from exc

        try:
            decoded = response.json()
            body = decoded if isinstance(decoded, dict) else {}
        except ValueError:
            body = {}
        if response.is_success:
            return body
        raise self._error_from_response(response, body)

    async def get_account(
        self,
        access_token: str,
        *,
        account_id: str,
        api_version: object = INSTAGRAM_DEFAULT_API_VERSION,
    ) -> dict[str, Any]:
        return await self._request(
            "GET",
            self._url(account_id, api_version=api_version),
            access_token=access_token,
            params={"fields": "id,username"},
        )

    async def send_text(
        self,
        access_token: str,
        *,
        account_id: str,
        recipient_id: str,
        text: str,
        api_version: object = INSTAGRAM_DEFAULT_API_VERSION,
    ) -> str:
        recipient = recipient_id.strip()
        if not recipient:
            raise InstagramAPIError("Instagram recipient ID is unavailable")
        body = await self._request(
            "POST",
            self._url(account_id, api_version=api_version, suffix="/messages"),
            access_token=access_token,
            json={"recipient": {"id": recipient}, "message": {"text": text}},
        )
        message_id = body.get("message_id")
        if not message_id:
            raise InstagramAPIError("Instagram accepted the request without returning a message ID")
        return str(message_id)


instagram_client = InstagramMessagingClient()
