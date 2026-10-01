from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from test_education_channel_runtime import _seed_authorized_student

from northstar_api.database import SessionFactory
from northstar_api.education_batches import EducationBatch
from northstar_api.education_enrollments import EducationEnrollment
from northstar_api.models import (
    Agent,
    Message,
    MessageRole,
    WhatsAppConnection,
    WhatsAppInboundMessage,
    Workspace,
)
from northstar_api.routers.whatsapp import _mark_dispatch_failure, _mark_dispatched
from northstar_api.services import workspace_dates
from northstar_api.services.chat import whatsapp_welcome
from northstar_api.services.education_chat import education_chat_coordinator
from northstar_api.services.whatsapp import token_cipher, whatsapp_client
from northstar_api.services.workspace_dates import local_calendar_date
from northstar_api.workers.tasks import _process_whatsapp_inbound_async

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("crm_test_plan")]


def test_workspace_dates_follow_local_midnight_and_end_of_day():
    now = datetime(2026, 9, 14, 20, 56, tzinfo=UTC)
    assert local_calendar_date("Asia/Calcutta", now) == date(2026, 9, 15)
    assert local_calendar_date("America/New_York", now) == date(2026, 9, 14)
    assert local_calendar_date("Asia/Calcutta", datetime(2026, 9, 15, 18, 29, tzinfo=UTC)) == date(
        2026, 9, 15
    )
    assert local_calendar_date("Asia/Calcutta", datetime(2026, 9, 15, 18, 30, tzinfo=UTC)) == date(
        2026, 9, 16
    )


def test_only_short_greetings_use_configured_welcome():
    agent = SimpleNamespace(
        name="CMA",
        language="English",
        appearance={"welcomeMessage": "Which course topic would you like to study?"},
    )
    assert (
        whatsapp_welcome(agent, " Hi! ")
        == "Hi! Welcome to CMA.\n\nWhich course topic would you like to study?"
    )
    assert whatsapp_welcome(agent, "hello, explain course fees") is None
    assert whatsapp_welcome(agent, "Hii") == whatsapp_welcome(agent, "Hi")
    assert whatsapp_welcome(agent, "Hiii!") == whatsapp_welcome(agent, "Hi")
    assert whatsapp_welcome(agent, "higher accounting") is None


async def test_verified_student_gets_welcome_at_india_midnight_without_model(
    client, auth_headers, monkeypatch
):
    seeded, _ = await _seed_authorized_student(client, auth_headers)

    class IndiaMidnight(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 14, 20, 56, tzinfo=UTC)

    monkeypatch.setattr(workspace_dates, "datetime", IndiaMidnight)
    async with SessionFactory() as session:
        agent = await session.get(Agent, UUID(seeded["agentId"]))
        workspace = await session.get(Workspace, agent.workspace_id)
        workspace.timezone = "Asia/Calcutta"
        agent.appearance = {
            **agent.appearance,
            "welcomeMessage": "Which course topic would you like to study?",
        }
        batch = await session.get(EducationBatch, UUID(seeded["batchId"]))
        batch.starts_on = date(2026, 9, 15)
        enrollment = await session.get(EducationEnrollment, UUID(seeded["enrollmentId"]))
        enrollment.starts_on = date(2026, 9, 15)
        connection = WhatsAppConnection(
            tenant_id=agent.tenant_id,
            workspace_id=agent.workspace_id,
            agent_id=agent.id,
            waba_id="welcome-test",
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
            message_text="Hii",
            provider_timestamp=datetime.now(UTC),
            status="queued",
        )
        session.add(receipt)
        await session.commit()
        receipt_id, tenant_id = receipt.id, agent.tenant_id
    retrieve = AsyncMock(side_effect=AssertionError("A greeting must not retrieve knowledge"))
    generate = AsyncMock(side_effect=AssertionError("A greeting must not require a provider key"))
    sender = AsyncMock(return_value="welcome-provider-id")
    monkeypatch.setattr(education_chat_coordinator.retrieval, "retrieve", retrieve)
    monkeypatch.setattr(education_chat_coordinator.model, "generate_grounded", generate)
    monkeypatch.setattr(token_cipher, "decrypt", lambda _: "test-token")
    monkeypatch.setattr(whatsapp_client, "send_text", sender)
    await _process_whatsapp_inbound_async(receipt_id)
    sender.assert_awaited_once()
    sent = sender.call_args.kwargs
    assert sent["to"] == seeded["phone"].lstrip("+")
    assert "Welcome to" in sent["text"]
    assert "Which course topic would you like to study?" in sent["text"]
    retrieve.assert_not_awaited()
    generate.assert_not_awaited()
    async with SessionFactory() as session:
        saved = await session.get(WhatsAppInboundMessage, receipt_id)
        assert saved.status == "processed", saved.last_error
        reply = await session.scalar(
            select(Message).where(
                Message.conversation_id == saved.conversation_id, Message.role == MessageRole.ASSISTANT
            )
        )
        assert reply.content == sent["text"]
        # A late webhook dispatcher result cannot erase completed worker state.
        await _mark_dispatch_failure(session, receipt_id, tenant_id)
        await _mark_dispatched(session, receipt_id, tenant_id)
        await session.refresh(saved)
        assert saved.status == "processed"
        assert saved.last_error is None
    await _process_whatsapp_inbound_async(receipt_id)
    sender.assert_awaited_once()


async def test_future_batch_still_rejects_greeting_without_private_content(client, auth_headers, monkeypatch):
    seeded, _ = await _seed_authorized_student(client, auth_headers)
    async with SessionFactory() as session:
        agent = await session.get(Agent, UUID(seeded["agentId"]))
        batch = await session.get(EducationBatch, UUID(seeded["batchId"]))
        batch.starts_on = date(2099, 1, 1)
        batch.ends_on = None
        connection = WhatsAppConnection(
            tenant_id=agent.tenant_id,
            workspace_id=agent.workspace_id,
            agent_id=agent.id,
            waba_id="future-test",
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
            message_text="Hi",
            provider_timestamp=datetime.now(UTC),
            status="queued",
        )
        session.add(receipt)
        await session.commit()
        receipt_id = receipt.id
    sender = AsyncMock(return_value="denied-provider-id")
    monkeypatch.setattr(token_cipher, "decrypt", lambda _: "test-token")
    monkeypatch.setattr(whatsapp_client, "send_text", sender)
    prepare = AsyncMock(side_effect=AssertionError("Future enrollment must not start chat"))
    monkeypatch.setattr(education_chat_coordinator, "prepare", prepare)
    await _process_whatsapp_inbound_async(receipt_id)
    prepare.assert_not_awaited()
    async with SessionFactory() as session:
        receipt = await session.get(WhatsAppInboundMessage, receipt_id)
        assert receipt.status == "rejected"
        assert receipt.last_error == "Education access: batch_not_started"


@pytest.mark.parametrize("worker_status", ["processing", "processed", "rejected"])
async def test_late_dispatch_result_preserves_worker_state_from_another_session(
    client, auth_headers, worker_status
):
    workspace_response = await client.get("/api/v1/workspace", headers=auth_headers)
    assert workspace_response.status_code == 200
    async with SessionFactory() as webhook_session:
        workspace = await webhook_session.get(Workspace, UUID(workspace_response.json()["id"]))
        receipt = WhatsAppInboundMessage(
            tenant_id=workspace.tenant_id,
            workspace_id=workspace.id,
            phone_number_id=uuid4().hex,
            provider_message_id=uuid4().hex,
            sender_wa_id="919000000001",
            message_type="text",
            message_text="Hi",
            status="queued",
        )
        webhook_session.add(receipt)
        await webhook_session.commit()
        receipt_id, tenant_id = receipt.id, receipt.tenant_id
        async with SessionFactory() as worker_session:
            updated = await worker_session.get(WhatsAppInboundMessage, receipt_id)
            updated.status = worker_status
            updated.last_error = "Access rejected" if worker_status == "rejected" else None
            await worker_session.commit()
        # The webhook still holds the queued version while the worker has moved on.
        assert receipt.status == "queued"
        await _mark_dispatch_failure(webhook_session, receipt_id, tenant_id)
        await _mark_dispatched(webhook_session, receipt_id, tenant_id)
        await webhook_session.refresh(receipt)
        assert receipt.status == worker_status
        assert receipt.last_error == ("Access rejected" if worker_status == "rejected" else None)
