from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime
from typing import Any
from fastapi import HTTPException

from northstar_api.lead_crm.channels import (
    CanonicalInboundEvent,
    CanonicalMessage,
    CanonicalSender,
    ChannelConnectionContext,
    ChannelConnector,
    channel_registry,
)
from northstar_api.lead_crm.domain import ChannelProvider


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _timestamp_seconds(value: object) -> datetime | None:
    try:
        raw = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if raw > 10_000_000_000:
        raw /= 1000
    try:
        return datetime.fromtimestamp(raw, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _constant_time_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode(), right.encode())


class MetaMessagingConnector(ChannelConnector):
    def __init__(self, provider: ChannelProvider) -> None:
        self.provider = provider

    async def verify(
        self,
        context: ChannelConnectionContext,
        *,
        headers: dict[str, str],
        body: bytes,
    ) -> bool:
        secret = str(context.credentials.get("app_secret") or "")
        signature = headers.get("x-hub-signature-256", "")
        if not secret or not signature.startswith("sha256="):
            return False
        expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return _constant_time_equal(signature, expected)

    async def normalize(
        self,
        context: ChannelConnectionContext,
        *,
        payload: dict[str, Any],
        correlation_id: str,
        received_at: datetime,
        raw_event_id: uuid.UUID | None = None,
    ) -> list[CanonicalInboundEvent]:
        output: list[CanonicalInboundEvent] = []
        entries = payload.get("entry")
        if not isinstance(entries, list):
            return output
        for entry_value in entries:
            if not isinstance(entry_value, dict):
                continue
            entry = _as_dict(entry_value)
            entry_id = str(entry.get("id") or "")
            messaging = entry.get("messaging")
            if isinstance(messaging, list):
                for index, item_value in enumerate(messaging):
                    if not isinstance(item_value, dict):
                        continue
                    item = _as_dict(item_value)
                    sender = _as_dict(item.get("sender"))
                    message = _as_dict(item.get("message"))
                    message_id = str(message.get("mid") or "") or None
                    event_id = (
                        message_id or f"{entry_id}:{item.get('timestamp') or received_at.timestamp()}:{index}"
                    )
                    output.append(
                        CanonicalInboundEvent(
                            event_id=uuid.uuid4(),
                            tenant_id=context.tenant_id,
                            provider=self.provider,
                            connection_key=str(context.connection_id),
                            external_event_id=event_id,
                            event_type="message.received",
                            sender=CanonicalSender(external_id=str(sender.get("id") or "") or None),
                            message=CanonicalMessage(
                                external_message_id=message_id,
                                message_type=(
                                    "text"
                                    if isinstance(message.get("text"), str)
                                    else str(message.get("type") or "unknown")
                                ),
                                text=(
                                    str(message.get("text")) if isinstance(message.get("text"), str) else None
                                ),
                                provider_timestamp=_timestamp_seconds(item.get("timestamp")),
                            ),
                            correlation_id=correlation_id,
                            received_at=received_at,
                            conversation_reference=str(sender.get("id") or "") or None,
                            raw_event_id=raw_event_id,
                            metadata={"entryId": entry_id, "recipient": item.get("recipient")},
                        )
                    )
            changes = entry.get("changes")
            if isinstance(changes, list):
                for index, change_value in enumerate(changes):
                    if not isinstance(change_value, dict):
                        continue
                    change = _as_dict(change_value)
                    value = _as_dict(change.get("value"))
                    messages = value.get("messages")
                    contacts = value.get("contacts")
                    contact_name = None
                    if isinstance(contacts, list) and contacts and isinstance(contacts[0], dict):
                        profile = _as_dict(contacts[0].get("profile"))
                        contact_name = profile.get("name")
                    if not isinstance(messages, list):
                        continue
                    for message_index, message_value in enumerate(messages):
                        if not isinstance(message_value, dict):
                            continue
                        message = _as_dict(message_value)
                        sender_id = str(message.get("from") or "") or None
                        external_id = (
                            str(message.get("id") or "") or f"{entry_id}:change:{index}:{message_index}"
                        )
                        text_value = _as_dict(message.get("text"))
                        body_value = text_value.get("body")
                        output.append(
                            CanonicalInboundEvent(
                                event_id=uuid.uuid4(),
                                tenant_id=context.tenant_id,
                                provider=self.provider,
                                connection_key=str(context.connection_id),
                                external_event_id=external_id,
                                event_type="message.received",
                                sender=CanonicalSender(
                                    external_id=sender_id,
                                    name=str(contact_name) if contact_name else None,
                                    phone=sender_id if self.provider == ChannelProvider.WHATSAPP else None,
                                ),
                                message=CanonicalMessage(
                                    external_message_id=str(message.get("id") or "") or None,
                                    message_type=str(message.get("type") or "unknown"),
                                    text=str(body_value) if body_value is not None else None,
                                    provider_timestamp=_timestamp_seconds(message.get("timestamp")),
                                ),
                                correlation_id=correlation_id,
                                received_at=received_at,
                                conversation_reference=sender_id,
                                raw_event_id=raw_event_id,
                                metadata={"entryId": entry_id, "field": change.get("field")},
                            )
                        )
        return output

    async def health_check(self, context: ChannelConnectionContext) -> dict[str, str]:
        if self.provider == ChannelProvider.INSTAGRAM:
            access_token = str(context.credentials.get("access_token") or "")
            app_secret = str(context.credentials.get("app_secret") or "")
            verify_token = str(context.credentials.get("verify_token") or "")
            account_id = str(context.configuration.get("instagramAccountId") or "")
            if not access_token or not app_secret or not verify_token or not account_id:
                return {"status": "configuration_error"}
            from northstar_api.services.instagram import InstagramAPIError, instagram_client

            try:
                identity = await instagram_client.get_account(
                    access_token,
                    account_id=account_id,
                    api_version=context.configuration.get("apiVersion"),
                )
            except InstagramAPIError as exc:
                if exc.requires_reconnect:
                    return {"status": "auth_required"}
                if exc.retryable:
                    return {"status": "unhealthy"}
                return {"status": "configuration_error"}
            username = str(identity.get("username") or "")
            return {"status": "healthy", **({"username": username} if username else {})}

        if self.provider == ChannelProvider.FACEBOOK_MESSENGER:
            page_access_token = str(context.credentials.get("page_access_token") or "")
            app_secret = str(context.credentials.get("app_secret") or "")
            verify_token = str(context.credentials.get("verify_token") or "")
            page_id = str(context.configuration.get("pageId") or "")
            if not page_access_token or not app_secret or not verify_token or not page_id:
                return {"status": "configuration_error"}
            from northstar_api.services.facebook_messenger import MessengerAPIError, messenger_client

            try:
                identity = await messenger_client.get_page(
                    page_access_token,
                    page_id=page_id,
                    api_version=context.configuration.get("apiVersion"),
                )
            except MessengerAPIError as exc:
                if exc.requires_reconnect:
                    return {"status": "auth_required"}
                if exc.retryable:
                    return {"status": "unhealthy"}
                return {"status": "configuration_error"}
            page_name = str(identity.get("name") or "")
            return {"status": "healthy", **({"page": page_name} if page_name else {})}

        return await super().health_check(context)


class TelegramConnector(ChannelConnector):
    provider = ChannelProvider.TELEGRAM

    async def verify(
        self,
        context: ChannelConnectionContext,
        *,
        headers: dict[str, str],
        body: bytes,
    ) -> bool:
        expected = str(context.credentials.get("webhook_secret") or "")
        supplied = headers.get("x-telegram-bot-api-secret-token", "")
        return bool(expected and supplied and _constant_time_equal(expected, supplied))

    async def normalize(
        self,
        context: ChannelConnectionContext,
        *,
        payload: dict[str, Any],
        correlation_id: str,
        received_at: datetime,
        raw_event_id: uuid.UUID | None = None,
    ) -> list[CanonicalInboundEvent]:
        update_id = payload.get("update_id")
        message_value = (
            payload.get("message") or payload.get("edited_message") or payload.get("business_message")
        )
        if update_id is None or not isinstance(message_value, dict):
            return []
        message = _as_dict(message_value)
        sender = _as_dict(message.get("from"))
        chat = _as_dict(message.get("chat"))
        text = message.get("text") or message.get("caption")
        sender_name = (
            " ".join(
                part
                for part in (
                    str(sender.get("first_name") or "").strip(),
                    str(sender.get("last_name") or "").strip(),
                )
                if part
            )
            or None
        )
        message_id = message.get("message_id")
        return [
            CanonicalInboundEvent(
                event_id=uuid.uuid4(),
                tenant_id=context.tenant_id,
                provider=self.provider,
                connection_key=str(context.connection_id),
                external_event_id=str(update_id),
                event_type="message.received",
                sender=CanonicalSender(external_id=str(sender.get("id") or "") or None, name=sender_name),
                message=CanonicalMessage(
                    external_message_id=str(message_id) if message_id is not None else None,
                    message_type="text" if text is not None else "unknown",
                    text=str(text) if text is not None else None,
                    provider_timestamp=_timestamp_seconds(message.get("date")),
                ),
                correlation_id=correlation_id,
                received_at=received_at,
                conversation_reference=str(chat.get("id") or "") or None,
                raw_event_id=raw_event_id,
                metadata={"chatType": chat.get("type"), "username": sender.get("username"), "contact": message.get("contact"), "forwarded": bool(message.get("forward_origin") or message.get("forward_date"))},
            )
        ]

    async def health_check(self, context: ChannelConnectionContext) -> dict[str, str]:
        bot_token = str(context.credentials.get("bot_token") or "")
        webhook_secret = str(context.credentials.get("webhook_secret") or "")
        if not bot_token or not webhook_secret:
            return {"status": "configuration_error"}
        from northstar_api.services.telegram import TelegramAPIError, telegram_client

        try:
            identity = await telegram_client.get_me(bot_token)
            info = await telegram_client.get_webhook_info(bot_token)
            from urllib.parse import urlsplit

            from northstar_api.config import get_settings
            from northstar_api.services.telegram_provisioning import public_base

            url = str(info.get("url") or "")
            metadata = context.configuration.get("telegram", {})
            if not identity.get("id") or not identity.get("username"):
                return {"status": "configuration_error"}
            if metadata.get("botId") and str(identity.get("id")) != str(metadata["botId"]):
                return {"status": "auth_required"}
            if context.public_id:
                path = (
                    f"{get_settings().app_api_prefix}/webhooks/channels/"
                    f"{context.tenant_id}/telegram/{context.public_id}"
                )
                if get_settings().telegram_public_base_url:
                    expected_url = public_base() + path
                    if url != expected_url or info.get("last_error_message"):
                        await telegram_client.set_webhook(
                            bot_token,
                            url=expected_url,
                            secret_token=webhook_secret,
                        )
                        info = await telegram_client.get_webhook_info(bot_token)
                        url = str(info.get("url") or "")
                    if url != expected_url:
                        return {"status": "configuration_error"}
                elif (
                    not url
                    or info.get("last_error_message")
                    or metadata.get("managed")
                    or urlsplit(url).scheme != "https"
                    or urlsplit(url).path != path
                ):
                    return {"status": "configuration_error"}
            elif not url or info.get("last_error_message"):
                return {"status": "configuration_error"}
        except HTTPException:
            return {"status": "configuration_error"}
        except TelegramAPIError as exc:
            if exc.requires_reconnect:
                return {"status": "auth_required"}
            if exc.retryable:
                return {"status": "unhealthy"}
            return {"status": "configuration_error"}
        username = str(identity.get("username") or "")
        return {"status": "healthy", **({"username": username} if username else {})}


class SignedAPIConnector(ChannelConnector):
    def __init__(self, provider: ChannelProvider) -> None:
        self.provider = provider

    async def verify(
        self,
        context: ChannelConnectionContext,
        *,
        headers: dict[str, str],
        body: bytes,
    ) -> bool:
        secret = str(context.credentials.get("webhook_secret") or "")
        if not secret:
            return bool(context.configuration.get("allowUnsigned", False))
        supplied = headers.get("x-northstar-signature", "")
        expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return bool(supplied and _constant_time_equal(expected, supplied))

    async def normalize(
        self,
        context: ChannelConnectionContext,
        *,
        payload: dict[str, Any],
        correlation_id: str,
        received_at: datetime,
        raw_event_id: uuid.UUID | None = None,
    ) -> list[CanonicalInboundEvent]:
        external_event_id = str(payload.get("eventId") or payload.get("event_id") or "")
        if not external_event_id:
            stable = json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str).encode()
            external_event_id = hashlib.sha256(stable).hexdigest()
        sender = _as_dict(payload.get("sender"))
        message = _as_dict(payload.get("message"))
        message_text = message.get("text") if message else payload.get("messageText")
        timestamp = payload.get("timestamp") or message.get("timestamp")
        campaign_value = payload.get("campaign")
        metadata_value = payload.get("metadata")
        return [
            CanonicalInboundEvent(
                event_id=uuid.uuid4(),
                tenant_id=context.tenant_id,
                provider=self.provider,
                connection_key=str(context.connection_id),
                external_event_id=external_event_id,
                event_type=str(payload.get("eventType") or "message.received"),
                sender=CanonicalSender(
                    external_id=str(sender.get("externalId") or sender.get("id") or "") or None,
                    name=str(sender.get("name") or "") or None,
                    phone=str(sender.get("phone") or "") or None,
                    email=str(sender.get("email") or "") or None,
                ),
                message=CanonicalMessage(
                    external_message_id=str(message.get("id") or "") or None,
                    message_type=str(message.get("type") or "text"),
                    text=str(message_text) if message_text is not None else None,
                    provider_timestamp=_timestamp_seconds(timestamp),
                ),
                correlation_id=correlation_id,
                received_at=received_at,
                conversation_reference=str(payload.get("conversationId") or "") or None,
                campaign_attribution=_as_dict(campaign_value),
                raw_event_id=raw_event_id,
                metadata=_as_dict(metadata_value),
            )
        ]


def register_default_channel_connectors() -> None:
    connectors: tuple[ChannelConnector, ...] = (
        MetaMessagingConnector(ChannelProvider.WHATSAPP),
        MetaMessagingConnector(ChannelProvider.INSTAGRAM),
        MetaMessagingConnector(ChannelProvider.FACEBOOK_MESSENGER),
        TelegramConnector(),
        SignedAPIConnector(ChannelProvider.API),
        SignedAPIConnector(ChannelProvider.CUSTOM),
        SignedAPIConnector(ChannelProvider.WIDGET),
        SignedAPIConnector(ChannelProvider.SLACK),
    )
    registered = set(channel_registry._connectors)
    for connector in connectors:
        if connector.provider not in registered:
            channel_registry.register(connector)
            registered.add(connector.provider)
