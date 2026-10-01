"""Attach provider-backed message status without guessing from message timestamps."""
from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.models import (
    Channel,
    Conversation,
    MessageRole,
    WhatsAppDeliveryReceipt,
    WhatsAppInboundMessage,
    WhatsAppOutboundDelivery,
)
from northstar_api.schemas import ConversationOut, WhatsAppContactOut


def attach_contact_details(items: Sequence[ConversationOut], inbound: Sequence[WhatsAppInboundMessage]) -> None:
    """Expose only sender details supplied by a signed incoming WhatsApp event."""
    by_conversation: dict[object, list[WhatsAppInboundMessage]] = {}
    for receipt in inbound:
        by_conversation.setdefault(receipt.conversation_id, []).append(receipt)
    for item in items:
        receipts = by_conversation.get(item.id, [])
        if not receipts:
            continue
        def received_at(receipt: WhatsAppInboundMessage) -> datetime:
            timestamp = receipt.provider_timestamp or receipt.created_at
            return timestamp.replace(tzinfo=UTC) if timestamp.tzinfo is None else timestamp
        receipts.sort(key=received_at, reverse=True)
        latest = receipts[0]
        sender = latest.sender_wa_id.lstrip("+")
        item.whatsapp_contact = WhatsAppContactOut(
            phone_number="+" + sender,
            wa_id=sender,
            profile_name=next((receipt.sender_name for receipt in receipts if receipt.sender_name), None),
            last_message_at=received_at(latest),
            last_message_type=latest.message_type,
        )
        # Older conversations predate phone capture. Fill their display from
        # the original webhook without overwriting manually saved contact data.
        if not item.visitor_details.phone:
            item.visitor_details.phone = item.whatsapp_contact.phone_number


def delivery_status(state: str, provider_ids: list[str], receipts: dict[str, set[str]]) -> str:
    if state in {"failed", "dispatch_failed", "rejected", "reconnect_required", "cancelled"}:
        return "failed"
    if state not in {"processed", "sent"}:
        return "pending"
    if not provider_ids:
        return "unknown"
    statuses = [receipts.get(provider_id, set()) for provider_id in provider_ids]
    if any("failed" in status for status in statuses):
        return "failed"
    # A split reply is only read/delivered once every part has that evidence.
    if all("read" in status for status in statuses):
        return "read"
    if all(status & {"delivered", "read"} for status in statuses):
        return "delivered"
    return "sent"


async def attach_whatsapp_message_status(
    session: AsyncSession, rows: Sequence[Conversation], items: Sequence[ConversationOut],
) -> None:
    conversations = {row.id: row for row in rows if row.channel == Channel.WHATSAPP}
    if not conversations:
        return
    messages = {message.id: message for item in items if item.id in conversations for message in item.messages}
    tenants = {row.tenant_id for row in conversations.values()}
    workspaces = {row.workspace_id for row in conversations.values()}
    inbound = (await session.scalars(select(WhatsAppInboundMessage).where(
        WhatsAppInboundMessage.conversation_id.in_(conversations),
        WhatsAppInboundMessage.tenant_id.in_(tenants),
        WhatsAppInboundMessage.workspace_id.in_(workspaces),
    ))).all()
    attach_contact_details(items, inbound)
    if not messages:
        return
    outbound = (await session.scalars(select(WhatsAppOutboundDelivery).where(
        WhatsAppOutboundDelivery.message_id.in_(messages),
        WhatsAppOutboundDelivery.tenant_id.in_(tenants),
        WhatsAppOutboundDelivery.workspace_id.in_(workspaces),
    ))).all()
    # The coordinator reserves user + assistant rows together, using consecutive
    # sequence numbers. Match the inbound idempotency key, never content or time.
    inbound_by_key = {
        (row.conversation_id, "wa:" + hashlib.sha256(row.provider_message_id.encode()).hexdigest()): row
        for row in inbound
    }
    deliveries = [(row.message_id, row.status, row.provider_message_ids or [], row.connection_id) for row in outbound]
    for conversation in conversations.values():
        by_sequence = {message.sequence: message for message in conversation.messages}
        for message in conversation.messages:
            receipt = inbound_by_key.get((conversation.id, message.idempotency_key))
            assistant = by_sequence.get(message.sequence + 1)
            if message.role == MessageRole.USER and receipt and assistant and assistant.role == MessageRole.ASSISTANT:
                ids = receipt.outbound_message_ids or ([receipt.outbound_message_id] if receipt.outbound_message_id else [])
                deliveries.append((assistant.id, receipt.status, ids, receipt.connection_id))
    ids = {provider_id for _, _, provider_ids, _ in deliveries for provider_id in provider_ids}
    receipts: dict[object, dict[str, set[str]]] = {}
    if ids:
        evidence = (await session.scalars(select(WhatsAppDeliveryReceipt).where(
            WhatsAppDeliveryReceipt.provider_message_id.in_(ids),
            WhatsAppDeliveryReceipt.tenant_id.in_(tenants),
            WhatsAppDeliveryReceipt.workspace_id.in_(workspaces),
        ))).all()
        for receipt in evidence:
            receipts.setdefault(receipt.connection_id, {}).setdefault(receipt.provider_message_id, set()).add(receipt.status)
    for message_id, state, provider_ids, connection_id in deliveries:
        if message_id in messages:
            messages[message_id].delivery_status = delivery_status(state, provider_ids, receipts.get(connection_id, {}))
