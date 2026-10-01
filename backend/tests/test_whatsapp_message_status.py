import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from northstar_api.models import Channel, MessageRole
from northstar_api.schemas import MessageOut, VisitorDetails
from northstar_api.services.whatsapp_message_status import (
    attach_contact_details,
    attach_whatsapp_message_status,
    delivery_status,
)


@pytest.mark.parametrize(("state", "ids", "receipts", "expected"), [
    ("queued", [], {}, "pending"),
    ("processing", ["a"], {"a": {"read"}}, "pending"),
    ("sent", ["a"], {}, "sent"),
    ("processed", ["a"], {"a": {"read", "sent"}}, "read"),
    ("processed", ["a", "b"], {"a": {"read"}}, "sent"),
    ("processed", ["a", "b"], {"a": {"read"}, "b": {"delivered"}}, "delivered"),
    ("processed", ["a", "b"], {"a": {"read"}, "b": {"read"}}, "read"),
    ("processed", ["a"], {"a": {"failed"}}, "failed"),
    ("reconnect_required", [], {}, "failed"),
    ("sent", [], {}, "unknown"),
])
def test_provider_status_is_conservative(state, ids, receipts, expected):
    assert delivery_status(state, ids, receipts) == expected


async def test_matches_exact_inbound_key_and_human_message_not_content_or_timestamp():
    conversation_id, connection_id = uuid4(), uuid4()
    tenant_id, workspace_id = uuid4(), uuid4()
    ids = [uuid4() for _ in range(4)]
    key = "wa:" + hashlib.sha256(b"customer-message").hexdigest()
    messages = [SimpleNamespace(id=ids[i], sequence=i+1, role=role, idempotency_key=key if i == 0 else None)
                for i, role in enumerate([MessageRole.USER, MessageRole.ASSISTANT, MessageRole.AGENT, MessageRole.ASSISTANT])]
    conversation = SimpleNamespace(id=conversation_id, channel=Channel.WHATSAPP, tenant_id=tenant_id, workspace_id=workspace_id, messages=messages)
    outputs = [MessageOut(id=m.id, role=m.role, content="Same text", created_at=datetime.now(UTC)) for m in messages]
    inbound = SimpleNamespace(conversation_id=conversation_id, provider_message_id="customer-message", outbound_message_ids=["ai-reply"], connection_id=connection_id, status="processed", sender_wa_id="919876543210", sender_name="Anan", provider_timestamp=datetime.now(UTC), message_type="text")
    outbound = SimpleNamespace(message_id=ids[2], provider_message_ids=["human-reply"], connection_id=connection_id, status="sent")
    evidence = [SimpleNamespace(connection_id=connection_id, provider_message_id="ai-reply", status="read"),
                SimpleNamespace(connection_id=connection_id, provider_message_id="human-reply", status="delivered"),
                SimpleNamespace(connection_id=uuid4(), provider_message_id="human-reply", status="read")]
    session = SimpleNamespace(scalars=AsyncMock(side_effect=[SimpleNamespace(all=lambda: [inbound]), SimpleNamespace(all=lambda: [outbound]), SimpleNamespace(all=lambda: evidence)]))
    item = SimpleNamespace(id=conversation_id, messages=outputs, visitor_details=VisitorDetails())
    await attach_whatsapp_message_status(session, [conversation], [item])
    assert [message.delivery_status for message in outputs] == [None, "read", "delivered", None]
    assert session.scalars.await_count == 3
    assert item.whatsapp_contact.phone_number == "+919876543210"
    assert item.visitor_details.phone == "+919876543210"


def test_contact_details_use_latest_sender_evidence_and_preserve_manual_fields():
    conversation_id = uuid4()
    item = SimpleNamespace(id=conversation_id, visitor_details=VisitorDetails(phone="+14155550123", location="Saved address"))
    old = SimpleNamespace(conversation_id=conversation_id, sender_wa_id="919876543210", sender_name="Old name", provider_timestamp=datetime(2026, 9, 14, tzinfo=UTC), message_type="text")
    latest = SimpleNamespace(conversation_id=conversation_id, sender_wa_id="919876543210", sender_name="Current name", provider_timestamp=datetime(2026, 9, 15), message_type="button")
    attach_contact_details([item], [latest, old])
    assert item.whatsapp_contact.profile_name == "Current name"
    assert item.whatsapp_contact.last_message_type == "button"
    assert item.whatsapp_contact.phone_number == "+919876543210"
    assert item.visitor_details.phone == "+14155550123"
    assert item.visitor_details.location == "Saved address"


def test_missing_profile_name_does_not_erase_the_last_known_name():
    conversation_id = uuid4()
    item = SimpleNamespace(id=conversation_id, visitor_details=VisitorDetails())
    old = SimpleNamespace(conversation_id=conversation_id, sender_wa_id="919876543210", sender_name="Anan", provider_timestamp=datetime(2026, 9, 14, tzinfo=UTC), message_type="text")
    latest = SimpleNamespace(conversation_id=conversation_id, sender_wa_id="919876543210", sender_name=None, provider_timestamp=datetime(2026, 9, 15, tzinfo=UTC), message_type="text")
    attach_contact_details([item], [old, latest])
    assert item.whatsapp_contact.profile_name == "Anan"
