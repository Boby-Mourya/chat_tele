from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy import select

from northstar_api.database import SessionFactory
from northstar_api.education_student_identities import EducationStudentIdentity
from northstar_api.lead_crm.channel_providers import TelegramConnector
from northstar_api.lead_crm.channels import ChannelConnectionContext
from northstar_api.lead_crm.domain import ChannelProvider
from northstar_api.services.telegram_enrollment import CONTACT_KEYBOARD, DENIED, telegram_enrollment_notice


async def test_phone_enrollment_contact_validation_and_revocation(client, auth_headers):
    workspace = (await client.get("/api/v1/workspace", headers=auth_headers)).json()
    agent = SimpleNamespace(tenant_id=UUID(workspace["tenantId"]), workspace_id=UUID(workspace["id"]))
    phone = "+919811223344"
    created = await client.post(
        "/api/v1/education/students",
        headers=auth_headers,
        json={"studentNumber": "PHONE-ENROLL", "name": "Phone Student", "telegramPhoneNumber": phone},
    )
    assert created.status_code == 201
    student = created.json()
    assert student["telegramPhoneNumber"] == phone
    assert student["telegramVerified"] is False
    duplicate = await client.post(
        "/api/v1/education/students",
        headers=auth_headers,
        json={"studentNumber": "PHONE-DUP", "name": "Other Student", "telegramPhoneNumber": phone},
    )
    assert duplicate.status_code == 409
    sender = "9988776655"
    event = SimpleNamespace(
        sender=SimpleNamespace(external_id=sender),
        conversation_reference=sender,
        metadata={"chatType": "private"},
    )
    async with SessionFactory() as session:
        prompt = await telegram_enrollment_notice(session, event=event, agent=agent)
        assert prompt[1] == CONTACT_KEYBOARD
        event.metadata["contact"] = {"phone_number": phone, "user_id": "111111"}
        assert (await telegram_enrollment_notice(session, event=event, agent=agent))[0] == DENIED
        assert (
            await session.scalar(
                select(EducationStudentIdentity.id).where(
                    EducationStudentIdentity.student_id == UUID(student["id"])
                )
            )
            is None
        )
        event.metadata["contact"]["user_id"] = sender
        event.metadata["forwarded"] = True
        assert (await telegram_enrollment_notice(session, event=event, agent=agent))[0] == DENIED
        event.metadata["forwarded"] = False
        event.metadata["contact"]["phone_number"] = "+919800000000"
        assert (await telegram_enrollment_notice(session, event=event, agent=agent))[0] == DENIED
        event.metadata["contact"]["phone_number"] = phone.removeprefix("+")
        other_workspace = SimpleNamespace(tenant_id=agent.tenant_id, workspace_id=uuid4())
        assert (await telegram_enrollment_notice(session, event=event, agent=other_workspace))[0] == DENIED
        event.metadata["chatType"] = "group"
        assert await telegram_enrollment_notice(session, event=event, agent=agent) is None
        event.metadata["chatType"] = "private"
        result = await telegram_enrollment_notice(session, event=event, agent=agent)
        assert result[1] == {"remove_keyboard": True}
        await session.commit()
        event.metadata.pop("contact")
        assert await telegram_enrollment_notice(session, event=event, agent=agent) is None
    fetched = (await client.get(f"/api/v1/education/students/{student['id']}", headers=auth_headers)).json()
    assert fetched["telegramVerified"] is True
    updated = await client.patch(
        f"/api/v1/education/students/{student['id']}",
        headers=auth_headers,
        json={"telegramPhoneNumber": "+919811223345"},
    )
    assert updated.status_code == 200
    assert updated.json()["telegramVerified"] is False
    async with SessionFactory() as session:
        assert (await telegram_enrollment_notice(session, event=event, agent=agent))[1] == CONTACT_KEYBOARD
        event.metadata["contact"] = {"phone_number": "+919811223345", "user_id": sender}
        assert (await telegram_enrollment_notice(session, event=event, agent=agent))[1] == {
            "remove_keyboard": True
        }
        await session.commit()
        identity = await session.scalar(
            select(EducationStudentIdentity).where(EducationStudentIdentity.student_id == UUID(student["id"]))
        )
        identity.status = "revoked"
        await session.commit()
        assert (await telegram_enrollment_notice(session, event=event, agent=agent))[0] == DENIED
    invalid = await client.patch(
        f"/api/v1/education/students/{student['id']}",
        headers=auth_headers,
        json={"telegramPhoneNumber": "123456789"},
    )
    assert invalid.status_code == 422
    cleared = await client.patch(
        f"/api/v1/education/students/{student['id']}",
        headers=auth_headers,
        json={"telegramPhoneNumber": None},
    )
    assert cleared.status_code == 200 and cleared.json()["telegramPhoneNumber"] is None


async def test_normalize_contact_retains_self_contact_evidence():
    connector = TelegramConnector()
    context = ChannelConnectionContext(
        tenant_id=uuid4(),
        connection_id=uuid4(),
        provider=ChannelProvider.TELEGRAM,
        configuration={},
        credentials={},
    )
    events = await connector.normalize(
        context,
        payload={
            "update_id": 1,
            "message": {
                "message_id": 2,
                "from": {"id": 9988776655},
                "chat": {"id": 9988776655, "type": "private"},
                "contact": {"phone_number": "+919811223344", "user_id": 9988776655},
            },
        },
        correlation_id="phone-test",
        received_at=datetime.now(UTC),
    )
    assert events[0].metadata["contact"]["user_id"] == 9988776655
    assert events[0].message.text is None


async def test_telegram_keyboard_is_sent_to_provider(monkeypatch):
    from northstar_api.services.telegram import TelegramBotClient

    client = TelegramBotClient()
    captured = []

    async def request(token, method, payload):
        captured.append((method, payload))
        return {"message_id": 1}

    monkeypatch.setattr(client, "_request", request)
    await client.send_text("test-token", chat_id="9988776655", text="Verify", reply_markup=CONTACT_KEYBOARD)
    assert captured[0][1]["reply_markup"]["keyboard"][0][0]["request_contact"] is True


async def test_worker_queues_contact_keyboard_without_llm(client, auth_headers, monkeypatch):
    from northstar_api.lead_crm.channel_models import ChannelConnection, ChannelOutboundDelivery
    from northstar_api.lead_crm.channel_scope import WorkspaceChannelConnection
    from northstar_api.lead_crm.models import RawWebhookEvent
    from northstar_api.models import Agent
    from northstar_api.workers import channel_event_consumer as worker

    created = await client.post(
        "/api/v1/agents",
        headers=auth_headers,
        json={"name": "Phone verification bot", "purpose": "education", "deploymentChannel": "telegram"},
    )
    assert created.status_code == 201
    calls = []
    monkeypatch.setattr(worker.send_telegram_message, "apply_async", lambda **kw: calls.append(kw))

    async def forbidden(*args, **kwargs):
        raise AssertionError("Unverified messages must not reach the LLM")

    monkeypatch.setattr(worker.education_chat_coordinator, "prepare", forbidden)
    async with SessionFactory() as session:
        agent = await session.get(Agent, UUID(created.json()["id"]))
        connection = ChannelConnection(
            tenant_id=agent.tenant_id,
            provider="telegram",
            name="Phone test",
            status="healthy",
            configuration_json={"agentId": str(agent.id)},
        )
        session.add(connection)
        await session.flush()
        session.add(
            WorkspaceChannelConnection(
                tenant_id=agent.tenant_id,
                workspace_id=agent.workspace_id,
                agent_id=agent.id,
                connection_id=connection.id,
            )
        )
        payload = {
            "update_id": 701,
            "message": {
                "message_id": 701,
                "from": {"id": 9988776600},
                "chat": {"id": 9988776600, "type": "private"},
                "text": "/start",
            },
        }
        raw = RawWebhookEvent(
            tenant_id=agent.tenant_id,
            connection_key=str(connection.id),
            provider="telegram",
            external_event_id="701",
            event_type="message.received",
            payload_json=payload,
            payload_hash="phone-test",
            correlation_id="phone-test",
            verification_status="verified",
        )
        session.add(raw)
        await session.flush()
        context = ChannelConnectionContext(
            tenant_id=agent.tenant_id,
            connection_id=connection.id,
            provider=ChannelProvider.TELEGRAM,
            configuration={},
            credentials={},
        )
        event = (
            await TelegramConnector().normalize(
                context, payload=payload, correlation_id="phone-test", received_at=datetime.now(UTC)
            )
        )[0]
        await worker._process_education_message(
            session, raw=raw, connection=connection, canonical=event, agent=agent
        )
        delivery = await session.scalar(
            select(ChannelOutboundDelivery).where(ChannelOutboundDelivery.connection_id == connection.id)
        )
        assert delivery.reply_markup == CONTACT_KEYBOARD
        assert raw.processing_status == "processed"
        assert len(calls) == 1


async def test_staff_phone_confirmation_persists_and_resets(client, auth_headers):
    created = await client.post("/api/v1/education/students", headers=auth_headers,
        json={"studentNumber": "PHONE-CHECKBOX", "name": "Confirmed Student",
              "telegramPhoneNumber": "+919822334455", "telegramPhoneVerified": True})
    assert created.status_code == 201
    student = created.json()
    assert student["telegramPhoneVerified"] is True
    assert student["telegramVerified"] is False  # Staff confirmation does not invent an account ID.
    url = f"/api/v1/education/students/{student['id']}"
    fetched = await client.get(url, headers=auth_headers)
    assert fetched.json()["telegramPhoneVerified"] is True
    unchecked = await client.patch(url, headers=auth_headers, json={"telegramPhoneVerified": False})
    assert unchecked.json()["telegramPhoneVerified"] is False
    await client.patch(url, headers=auth_headers, json={"telegramPhoneVerified": True})
    changed = await client.patch(url, headers=auth_headers, json={"telegramPhoneNumber": "+919822334456"})
    assert changed.json()["telegramPhoneVerified"] is False
    cleared = await client.patch(url, headers=auth_headers, json={"telegramPhoneNumber": None, "telegramPhoneVerified": True})
    assert cleared.json()["telegramPhoneVerified"] is False
