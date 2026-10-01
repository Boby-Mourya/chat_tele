from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

SLACK_API_BASE = "https://slack.com/api"
SLACK_TEXT_LIMIT = 4000


@dataclass(slots=True)
class SlackAPIError(RuntimeError):
    message: str
    status_code: int | None = None
    provider_code: str | None = None
    retryable: bool = False
    requires_reconnect: bool = False
    retry_after_seconds: int | None = None

    def __str__(self) -> str:
        return self.message


def split_slack_text(text: str, limit: int = SLACK_TEXT_LIMIT) -> list[str]:
    value = text.strip()
    if not value:
        return []
    if limit < 1:
        raise ValueError("Slack text chunk limit must be positive")
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


def encode_slack_target(channel_id: str, thread_ts: str) -> str:
    channel = channel_id.strip()
    thread = thread_ts.strip()
    if not channel or "|" in channel:
        raise SlackAPIError("Slack channel ID is invalid")
    if not thread or "|" in thread:
        raise SlackAPIError("Slack thread timestamp is invalid")
    return f"{channel}|{thread}"


def decode_slack_target(value: str) -> tuple[str, str] | None:
    channel, separator, thread_ts = value.strip().partition("|")
    if not separator or not channel or not thread_ts:
        return None
    if not channel[0] in {"C", "D", "G"} or not channel[1:].isalnum():
        return None
    pieces = thread_ts.split(".", 1)
    if len(pieces) != 2 or not all(piece.isdigit() for piece in pieces):
        return None
    return channel, thread_ts


class SlackWebClient:
    def __init__(self, *, timeout_seconds: float = 10.0, api_base: str = SLACK_API_BASE) -> None:
        self.timeout_seconds = timeout_seconds
        self.api_base = api_base.rstrip("/")

    @staticmethod
    def _headers(bot_token: str) -> dict[str, str]:
        token = bot_token.strip()
        if not token:
            raise SlackAPIError("Slack bot token is not configured", requires_reconnect=True)
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }

    @staticmethod
    def _retry_after(response: httpx.Response) -> int | None:
        value = response.headers.get("retry-after")
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _error(
        response: httpx.Response,
        body: dict[str, Any],
    ) -> SlackAPIError:
        provider_code = str(body.get("error") or "slack_api_error")
        reconnect_codes = {
            "invalid_auth",
            "not_authed",
            "token_revoked",
            "token_expired",
            "account_inactive",
        }
        retryable_codes = {
            "ratelimited",
            "rate_limited",
            "internal_error",
            "fatal_error",
            "service_unavailable",
            "request_timeout",
        }
        status_code = response.status_code
        retryable = status_code == 429 or status_code >= 500 or provider_code in retryable_codes
        requires_reconnect = status_code in {401, 403} or provider_code in reconnect_codes
        return SlackAPIError(
            provider_code.replace("_", " "),
            status_code=status_code,
            provider_code=provider_code,
            retryable=retryable,
            requires_reconnect=requires_reconnect,
            retry_after_seconds=SlackWebClient._retry_after(response),
        )

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        bot_token: str,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.request(
                    method,
                    f"{self.api_base}/{endpoint.lstrip('/')}",
                    headers=self._headers(bot_token),
                    json=json,
                )
        except httpx.TimeoutException as exc:
            raise SlackAPIError("Slack request timed out", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise SlackAPIError("Slack network request failed", retryable=True) from exc

        try:
            decoded = response.json()
            body = decoded if isinstance(decoded, dict) else {}
        except ValueError:
            body = {}
        if response.is_success and body.get("ok") is True:
            return body
        raise self._error(response, body)

    async def auth_test(self, bot_token: str) -> dict[str, Any]:
        return await self._request("POST", "auth.test", bot_token=bot_token, json={})

    async def post_message(
        self,
        bot_token: str,
        *,
        channel_id: str,
        text: str,
        thread_ts: str | None = None,
    ) -> str:
        channel = channel_id.strip()
        if not channel:
            raise SlackAPIError("Slack channel ID is unavailable")
        message = text.strip()
        if not message:
            raise SlackAPIError("Slack message text is empty")
        payload: dict[str, Any] = {"channel": channel, "text": message}
        if thread_ts:
            payload["thread_ts"] = thread_ts.strip()
        body = await self._request(
            "POST",
            "chat.postMessage",
            bot_token=bot_token,
            json=payload,
        )
        message_ts = body.get("ts")
        if not message_ts:
            raise SlackAPIError("Slack accepted the request without returning a message timestamp")
        return str(message_ts)


slack_client = SlackWebClient()
