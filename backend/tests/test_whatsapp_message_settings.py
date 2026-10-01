from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from test_education_channel_runtime import _seed_authorized_student

from northstar_api.database import SessionFactory
from northstar_api.models import (
    Agent,
    Channel,
    Message,
    MessageRole,
    WhatsAppConnection,
    WhatsAppInboundMessage,
)
from northstar_api.schemas import ChatStreamRequest, WhatsAppMessageSettings
from northstar_api.services.chat import ChatCoordinator, whatsapp_welcome
from northstar_api.services.education_chat import education_chat_coordinator
from northstar_api.services.localization import localized_no_evidence
from northstar_api.services.whatsapp import split_whatsapp_text, token_cipher, whatsapp_client
from northstar_api.services.whatsapp_messages import format_whatsapp_reply
from northstar_api.workers.tasks import _process_whatsapp_inbound_async

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("crm_test_plan")]


def test_long_monospace_answers_keep_formatting_in_each_provider_message():
    text = "```" + "Account detail " * 750 + "```"
    chunks = split_whatsapp_text(text)
    assert len(chunks) > 1
    assert all(len(chunk) <= 4096 and chunk.startswith("```") and chunk.endswith("```") for chunk in chunks)
    assert " ".join(chunk.strip("`").strip() for chunk in chunks) == text.strip("`").strip()


def test_welcome_is_exact_and_can_be_disabled():
    settings = {
        "welcomeEnabled": True,
        "welcomeMessage": "*Welcome!*\n\nChoose a topic.",
        "replyTemplate": "*{bot_name}*\n{message}",
    }
    agent = SimpleNamespace(name="CMA", language="English", appearance={"whatsapp": settings})
    assert whatsapp_welcome(agent, "Hi!") == "*Welcome!*\n\nChoose a topic."
    assert whatsapp_welcome(agent, "Hello, explain accounting") is None
    settings["welcomeEnabled"] = False
    assert whatsapp_welcome(agent, "Hi!") is None


def test_code_examples_and_chunk_indentation_remain_literal():
    agent = SimpleNamespace(name="CMA", appearance={})
    code = "```python\n# comment\nvalue = 2 ** 4\n    print(value)\n```"
    assert format_whatsapp_reply(agent, "**Example**\n" + code) == "*Example*\n" + code.replace(
        "```python", "```"
    )
    assert format_whatsapp_reply(agent, "`**literal**`") == "`**literal**`"
    long_code = "```" + "\n    indented_line = 1" * 700 + "\n```"
    chunks = split_whatsapp_text(long_code)
    assert all(len(chunk) <= 4096 for chunk in chunks)
    assert "".join(chunk[3:-3] for chunk in chunks) == long_code[3:-3]


def test_reply_structure_uses_whatsapp_markers_without_replacing_answer_tokens():
    agent = SimpleNamespace(
        name="CMA", appearance={"whatsapp": {"replyTemplate": "*{bot_name}*\n\n{message}\n\n_Thank you_"}}
    )
    assert (
        format_whatsapp_reply(
            agent, "## Overview\n**Important**\n[Help](https://example.com)\nUse {bot_name}"
        )
        == "*CMA*\n\n*Overview*\n*Important*\nHelp: https://example.com\nUse {bot_name}\n\n_Thank you_"
    )


def test_whatsapp_hides_internal_source_markers() -> None:
    agent = SimpleNamespace(name="CMA", appearance={})
    assert (
        format_whatsapp_reply(agent, "CMA USA is administered by IMA [S1][S2].")
        == "CMA USA is administered by IMA."
    )


@pytest.mark.parametrize(
    "template", ["missing answer", "{message}{message}", "{message}\n{email}", "{{message}}"]
)
def test_invalid_reply_structure_is_rejected(template):
    with pytest.raises(ValidationError):
        WhatsAppMessageSettings(reply_template=template)


@pytest.mark.parametrize("incoming,enabled", [("Hi", True), ("Explain the topic", True), ("Hi", False)])
async def test_saved_settings_are_used_in_education_whatsapp_delivery(
    client, auth_headers, monkeypatch, incoming, enabled
):
    seeded, headers = await _seed_authorized_student(client, auth_headers)
    agent_id = seeded["agentId"]
    response = await client.get(f"/api/v1/agents/{agent_id}", headers=headers)
    original = response.json()["appearance"]
    settings = {
        "welcomeEnabled": enabled,
        "welcomeMessage": "*Welcome to CMA!*\n\n- Ask a question\n- Review your lesson",
        "replyTemplate": "*{bot_name}*\n\n{message}\n\n_Keep learning!_",
    }
    saved = await client.patch(
        f"/api/v1/agents/{agent_id}", headers=headers, json={"appearance": {**original, "whatsapp": settings}}
    )
    assert saved.status_code == 200, saved.text
    reloaded = (await client.get(f"/api/v1/agents/{agent_id}", headers=headers)).json()
    assert reloaded["appearance"]["whatsapp"] == settings
    assert reloaded["appearance"]["welcomeMessage"] == original["welcomeMessage"]
    invalid = await client.patch(
        f"/api/v1/agents/{agent_id}",
        headers=headers,
        json={"appearance": {**original, "whatsapp": {**settings, "replyTemplate": "No answer placeholder"}}},
    )
    assert invalid.status_code == 422
    async with SessionFactory() as session:
        agent = await session.get(Agent, UUID(agent_id))
        connection = WhatsAppConnection(
            tenant_id=agent.tenant_id,
            workspace_id=agent.workspace_id,
            agent_id=agent.id,
            waba_id="format-test",
            phone_number_id=uuid4().hex,
            access_token_encrypted=b"test",
            status="connected",
        )
        session.add(connection)
        await session.flush()
        receipt = WhatsAppInboundMessage(
            tenant_id=agent.tenant_id,
            workspace_id=agent.workspace_id,
            connection_id=connection.id,
            phone_number_id=connection.phone_number_id,
            provider_message_id=uuid4().hex,
            sender_wa_id=seeded["phone"].lstrip("+"),
            message_type="text",
            message_text=incoming,
            provider_timestamp=datetime.now(UTC),
            status="queued",
        )
        session.add(receipt)
        await session.commit()
        receipt_id = receipt.id
    retrieval = AsyncMock(return_value=[])
    monkeypatch.setattr(education_chat_coordinator.retrieval, "retrieve", retrieval)
    monkeypatch.setattr(
        education_chat_coordinator.model,
        "generate_grounded",
        AsyncMock(side_effect=AssertionError("No live model calls in this test")),
    )
    sender = AsyncMock(return_value="formatted-reply-id")
    monkeypatch.setattr(token_cipher, "decrypt", lambda _: "test-token")
    monkeypatch.setattr(whatsapp_client, "send_text", sender)
    await _process_whatsapp_inbound_async(receipt_id)
    sender.assert_awaited_once()
    sent = sender.call_args.kwargs["text"]
    if incoming == "Hi" and enabled:
        assert sent == settings["welcomeMessage"]
        retrieval.assert_not_awaited()
    else:
        assert sent == f"*{reloaded['name']}*\n\n{localized_no_evidence('English')}\n\n_Keep learning!_"
        retrieval.assert_awaited_once()
    async with SessionFactory() as session:
        receipt = await session.get(WhatsAppInboundMessage, receipt_id)
        assert receipt.status == "processed", receipt.last_error
        message = await session.scalar(
            select(Message).where(
                Message.conversation_id == receipt.conversation_id, Message.role == MessageRole.ASSISTANT
            )
        )
        assert message.content == sent
    await _process_whatsapp_inbound_async(receipt_id)
    sender.assert_awaited_once()


async def test_website_answers_do_not_use_whatsapp_structure(client, auth_headers):
    created = await client.post(
        "/api/v1/agents", headers=auth_headers, json={"name": "Website format isolation"}
    )
    assert created.status_code == 201, created.text
    data = created.json()
    patched = await client.patch(
        f"/api/v1/agents/{data['id']}",
        headers=auth_headers,
        json={
            "appearance": {
                **data["appearance"],
                "whatsapp": {
                    "welcomeEnabled": True,
                    "welcomeMessage": "Only on WhatsApp",
                    "replyTemplate": "*WhatsApp*\n{message}",
                },
            }
        },
    )
    assert patched.status_code == 200, patched.text
    coordinator = ChatCoordinator(retrieval=SimpleNamespace(retrieve=AsyncMock(return_value=[])))
    async with SessionFactory() as session:
        agent = await session.get(Agent, UUID(data["id"]))
        prepared = await coordinator.prepare(
            session,
            tenant_id=agent.tenant_id,
            workspace_id=agent.workspace_id,
            request=ChatStreamRequest(agent_id=agent.id, message="Hi", visitor_id=uuid4().hex),
            channel=Channel.WIDGET,
        )
        assert prepared.answer == localized_no_evidence("English")
