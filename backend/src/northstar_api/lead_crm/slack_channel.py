from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from northstar_api.lead_crm.channels import (
    CanonicalInboundEvent,
    CanonicalMessage,
    CanonicalSender,
    ChannelConnectionContext,
    ChannelConnector,
)
from northstar_api.lead_crm.domain import ChannelProvider
from northstar_api.services.slack import SlackAPIError, slack_client

SLACK_SIGNATURE_VERSION = "v0"
SLACK_SIGNATURE_TOLERANCE_SECONDS = 300


def _slack_timestamp(value: object) -> datetime | None:
    try:
        return datetime.fromtimestamp(float(str(value)), tz=UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _safe_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


class SlackConnector(ChannelConnector):
    provider = ChannelProvider.SLACK

    async def verify(
        self,
        context: ChannelConnectionContext,
        *,
        headers: dict[str, str],
        body: bytes,
    ) -> bool:
        signing_secret = str(context.credentials.get("signing_secret") or "")
        timestamp = headers.get("x-slack-request-timestamp", "")
        supplied = headers.get("x-slack-signature", "")
        if not signing_secret or not timestamp or not supplied.startswith(f"{SLACK_SIGNATURE_VERSION}="):
            return False
        try:
            request_timestamp = int(timestamp)
        except ValueError:
            return False
        if abs(int(time.time()) - request_timestamp) > SLACK_SIGNATURE_TOLERANCE_SECONDS:
            return False
        base = f"{SLACK_SIGNATURE_VERSION}:{timestamp}:".encode() + body
        expected = (
            f"{SLACK_SIGNATURE_VERSION}="
            + hmac.new(signing_secret.encode(), base, hashlib.sha256).hexdigest()
        )
        return hmac.compare_digest(expected.encode(), supplied.encode())

    async def normalize(
        self,
        context: ChannelConnectionContext,
        *,
        payload: dict[str, Any],
        correlation_id: str,
        received_at: datetime,
        raw_event_id: uuid.UUID | None = None,
    ) -> list[CanonicalInboundEvent]:
        if payload.get("type") != "event_callback":
            return []
        event = _safe_dict(payload.get("event"))
        event_type = str(event.get("type") or "")
        if event_type not in {"message", "app_mention"}:
            return []
        if event.get("bot_id") or event.get("bot_profile"):
            return []
        subtype = str(event.get("subtype") or "")
        if subtype and subtype != "thread_broadcast":
            return []

        channel_id = str(event.get("channel") or "").strip()
        event_ts = str(event.get("ts") or "").strip()
        if not channel_id or not event_ts:
            return []
        thread_ts = str(event.get("thread_ts") or event_ts).strip()
        sender_id = str(event.get("user") or "").strip() or None
        text = event.get("text")
        message_text = str(text) if isinstance(text, str) else None
        external_message_id = str(event.get("client_msg_id") or event_ts)
        external_event_id = str(payload.get("event_id") or external_message_id)
        user_profile = _safe_dict(event.get("user_profile"))
        sender_name = str(
            user_profile.get("display_name")
            or user_profile.get("real_name")
            or ""
        ).strip() or None

        return [
            CanonicalInboundEvent(
                event_id=uuid.uuid4(),
                tenant_id=context.tenant_id,
                provider=self.provider,
                connection_key=str(context.connection_id),
                external_event_id=external_event_id,
                event_type="message.received",
                sender=CanonicalSender(external_id=sender_id, name=sender_name),
                message=CanonicalMessage(
                    external_message_id=external_message_id,
                    message_type="text" if message_text is not None else "unknown",
                    text=message_text,
                    provider_timestamp=_slack_timestamp(event_ts),
                ),
                correlation_id=correlation_id,
                received_at=received_at,
                conversation_reference=f"{channel_id}|{thread_ts}",
                raw_event_id=raw_event_id,
                metadata={
                    "teamId": payload.get("team_id"),
                    "apiAppId": payload.get("api_app_id"),
                    "channelId": channel_id,
                    "threadTs": thread_ts,
                    "eventTs": event_ts,
                    "slackEventType": event_type,
                },
            )
        ]

    async def health_check(self, context: ChannelConnectionContext) -> dict[str, str]:
        bot_token = str(context.credentials.get("bot_token") or "")
        signing_secret = str(context.credentials.get("signing_secret") or "")
        if not bot_token or not signing_secret:
            return {"status": "configuration_error"}
        try:
            identity = await slack_client.auth_test(bot_token)
        except SlackAPIError as exc:
            if exc.requires_reconnect:
                return {"status": "auth_required"}
            if exc.retryable:
                return {"status": "unhealthy"}
            return {"status": "configuration_error"}
        team = str(identity.get("team") or "")
        bot_user = str(identity.get("user") or "")
        result = {"status": "healthy"}
        if team:
            result["team"] = team
        if bot_user:
            result["user"] = bot_user
        return result
