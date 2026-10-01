from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

TELEGRAM_API_BASE = "https://api.telegram.org"
TELEGRAM_TEXT_LIMIT = 4096


@dataclass(slots=True)
class TelegramAPIError(RuntimeError):
    message: str
    status_code: int | None = None
    retryable: bool = False
    requires_reconnect: bool = False
    retry_after_seconds: int | None = None

    def __str__(self) -> str:
        return self.message


def split_telegram_text(text: str, limit: int = TELEGRAM_TEXT_LIMIT) -> list[str]:
    value = text.strip()
    if not value:
        return []
    if limit < 1:
        raise ValueError("Telegram text chunk limit must be positive")
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


class TelegramBotClient:
    def __init__(self, *, timeout_seconds: float = 10.0) -> None:
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _method_url(bot_token: str, method: str) -> str:
        token = bot_token.strip()
        if not token:
            raise TelegramAPIError("Telegram bot token is not configured", requires_reconnect=True)
        return f"{TELEGRAM_API_BASE}/bot{token}/{method}"

    async def _request(self, bot_token: str, method: str, payload: dict[str, Any] | None = None) -> Any:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(self._method_url(bot_token, method), json=payload or {})
        except httpx.TimeoutException:
            raise TelegramAPIError("Telegram request timed out", retryable=True) from None
        except httpx.HTTPError:
            raise TelegramAPIError("Telegram network request failed", retryable=True) from None

        body: dict[str, Any]
        try:
            decoded = response.json()
            body = decoded if isinstance(decoded, dict) else {}
        except ValueError:
            body = {}

        if response.is_success and body.get("ok") is True:
            result = body.get("result")
            return result

        error_code = body.get("error_code")
        try:
            status_code = int(error_code) if error_code is not None else response.status_code
        except (TypeError, ValueError):
            status_code = response.status_code
        # Provider descriptions and HTTP exceptions can contain credential-bearing URLs.
        description = f"Telegram request failed (code {status_code})"
        parameters = body.get("parameters") if isinstance(body.get("parameters"), dict) else {}
        retry_after = parameters.get("retry_after")
        try:
            retry_after_seconds = int(retry_after) if retry_after is not None else None
        except (TypeError, ValueError):
            retry_after_seconds = None
        reconnect = status_code in {401, 403}
        retryable = status_code == 429 or status_code >= 500
        raise TelegramAPIError(
            description,
            status_code=status_code,
            retryable=retryable,
            requires_reconnect=reconnect,
            retry_after_seconds=retry_after_seconds,
        )

    async def get_me(self, bot_token: str) -> dict[str, Any]:
        result = await self._request(bot_token, "getMe")
        if not isinstance(result, dict):
            raise TelegramAPIError("Telegram returned an invalid bot identity")
        return result

    async def get_managed_bot_token(self, manager_token: str, bot_id: str) -> str:
        token = await self._request(manager_token, "getManagedBotToken", {"user_id": int(bot_id)})
        if not isinstance(token, str) or not token:
            raise TelegramAPIError("Telegram did not return a managed bot token")
        return token

    async def set_webhook(
        self, bot_token: str, *, url: str, secret_token: str, allowed_updates: list[str] | None = None
    ) -> None:
        result = await self._request(
            bot_token,
            "setWebhook",
            {
                "url": url,
                "secret_token": secret_token,
                "allowed_updates": allowed_updates or ["message", "edited_message", "business_message"],
            },
        )
        if result is not True:
            raise TelegramAPIError("Telegram webhook registration was not acknowledged")

    async def delete_webhook(self, bot_token: str) -> None:
        if await self._request(bot_token, "deleteWebhook", {"drop_pending_updates": True}) is not True:
            raise TelegramAPIError("Telegram did not acknowledge webhook removal")

    async def get_webhook_info(self, bot_token: str) -> dict[str, Any]:
        result = await self._request(bot_token, "getWebhookInfo")
        if not isinstance(result, dict):
            raise TelegramAPIError("Telegram returned invalid webhook information")
        return result

    async def allow_managed_bot_students(self, manager_token: str, bot_id: str) -> None:
        result = await self._request(manager_token, "setManagedBotAccessSettings", {
            "user_id": int(bot_id), "is_access_restricted": False,
        })
        if result is not True:
            raise TelegramAPIError("Telegram could not enable student access")

    async def answer_callback(self, bot_token: str, callback_id: str) -> None:
        await self._request(bot_token, "answerCallbackQuery", {"callback_query_id": callback_id})

    async def send_text(
        self, bot_token: str, *, chat_id: str, text: str, reply_markup: dict[str, Any] | None = None
    ) -> str:
        result = await self._request(
            bot_token,
            "sendMessage",
            {"chat_id": chat_id, "text": text, **({"reply_markup": reply_markup} if reply_markup else {})},
        )
        message_id = result.get("message_id")
        if message_id is None:
            raise TelegramAPIError("Telegram accepted the request without returning a message ID")
        return str(message_id)


telegram_client = TelegramBotClient()
