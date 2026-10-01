from __future__ import annotations

import asyncio
import signal
from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog
from aiokafka import AIOKafkaConsumer  # type: ignore[import-untyped]
from aiokafka.structs import TopicPartition  # type: ignore[import-untyped]
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from northstar_api.agent_purpose import AgentPurpose, get_agent_purpose
from northstar_api.config import get_settings
from northstar_api.database import build_engine, set_tenant_context
from northstar_api.education_conversation_context import EducationConversationContext
from northstar_api.education_papers import EducationPaper
from northstar_api.lead_crm.channel_models import ChannelConnection, ChannelOutboundDelivery
from northstar_api.lead_crm.channel_scope import WorkspaceChannelConnection
from northstar_api.lead_crm.channels import CanonicalInboundEvent, ChannelConnectionContext, channel_registry
from northstar_api.lead_crm.credentials import CredentialStoreError, credential_store
from northstar_api.lead_crm.domain import ChannelProvider, LeadLifecycleStatus, QualificationStatus
from northstar_api.lead_crm.models import LeadActivityEvent, LeadProfile, RawWebhookEvent
from northstar_api.lead_crm.qualification import lead_qualification_engine
from northstar_api.lead_crm.services import lead_domain_service
from northstar_api.logging import configure_logging
from northstar_api.models import (
    Agent,
    AgentStatus,
    Channel,
    Conversation,
    ConversationState,
    Lead,
    Message,
    MessageRole,
    ProcessedEvent,
)
from northstar_api.schemas import ChatStreamRequest
from northstar_api.services.chat import PreparedChat
from northstar_api.services.notifications import notify_workspace_admins
from northstar_api.services.education_chat import education_chat_coordinator
from northstar_api.services.education_conversation_policy import education_source
from northstar_api.services.education_runtime_authorization import (
    EducationAccessDecision,
    EducationAccessReason,
    authorize_education_access,
    identity_candidate_for_event,
)
from northstar_api.services.entitlements import EntitlementError, require_capacity, require_channel
from northstar_api.services.outbox import enqueue_event
from northstar_api.workers.event_utils import EventEnvelope, parse_envelope, quarantine_event
from northstar_api.workers.telegram_tasks import send_telegram_message

_EDUCATION_PAPER_MODEL = EducationPaper
EDUCATION_COURSE_SETUP_REQUIRED = (
    "The institute has not configured curriculum and paper access for this enrollment"
)
EDUCATION_SETUP_NOTICE = (
    "Your course assistant is not ready to answer yet. Please contact your school or course administrator."
)

settings = get_settings()
configure_logging(settings)
logger = structlog.get_logger(__name__)
CONSUMER_NAME = "channel-lead-router-v1"
TOPICS = ["channel.event.received.v1"]


def _raw_event_id(event: EventEnvelope) -> UUID:
    try:
        return UUID(str(event.payload["rawEventId"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("channel event has no valid rawEventId") from exc


def _conversation_channel(provider: ChannelProvider) -> Channel:
    if provider == ChannelProvider.WHATSAPP:
        return Channel.WHATSAPP
    if provider == ChannelProvider.WIDGET:
        return Channel.WIDGET
    if provider == ChannelProvider.SLACK:
        return Channel.SLACK
    if provider == ChannelProvider.TELEGRAM:
        return Channel.TELEGRAM
    return Channel.API


def _visitor_key(event: CanonicalInboundEvent) -> str:
    source = event.conversation_reference or event.sender.external_id or event.external_event_id
    return f"{event.provider.value}:{source}"[:128]


def _message_idempotency_key(event: CanonicalInboundEvent) -> str:
    message_id = event.message.external_message_id if event.message else None
    return f"channel:{event.provider.value}:{event.connection_key}:{message_id or event.external_event_id}"[:128]


async def _queue_telegram_reply(
    session: AsyncSession,
    *,
    connection: ChannelConnection,
    event: CanonicalInboundEvent,
    prepared: PreparedChat,
    reply_markup: dict | None = None,
) -> None:
    chat_id = event.conversation_reference
    if not chat_id or not chat_id.removeprefix("-").isdigit():
        return
    message = await session.scalar(
        select(Message).where(
            Message.id == prepared.assistant_message_id,
            Message.tenant_id == event.tenant_id,
        )
    )
    if message is None or not message.content.strip():
        return
    delivery = ChannelOutboundDelivery(
        tenant_id=event.tenant_id,
        workspace_id=message.workspace_id,
        connection_id=connection.id,
        message_id=message.id,
        provider=ChannelProvider.TELEGRAM.value,
        reply_markup=reply_markup,
        recipient_external_id=chat_id,
        status="queued",
    )
    message.finish_reason = "queued"
    session.add(delivery)
    await session.commit()
    try:
        await asyncio.to_thread(
            send_telegram_message.apply_async,
            args=[str(delivery.id)],
            queue="telegram.outbound",
            routing_key="telegram.outbound",
        )
        delivery.dispatch_attempts += 1
        delivery.dispatched_at = datetime.now(UTC)
        delivery.next_dispatch_at = datetime.now(UTC) + timedelta(minutes=5)
        delivery.last_error = None
    except Exception:
        delivery.dispatch_attempts += 1
        delivery.status = "failed"
        delivery.next_dispatch_at = datetime.now(UTC)
        delivery.last_error = "queue dispatch unavailable"
    await session.commit()


async def _get_or_create_conversation(
    session: AsyncSession,
    *,
    event: CanonicalInboundEvent,
    agent: Agent,
) -> Conversation:
    visitor_id = _visitor_key(event)
    conversation = await session.scalar(
        select(Conversation)
        .where(
            Conversation.tenant_id == event.tenant_id,
            Conversation.workspace_id == agent.workspace_id,
            Conversation.agent_id == agent.id,
            Conversation.visitor_id == visitor_id,
            Conversation.state == ConversationState.OPEN,
        )
        .order_by(Conversation.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    if conversation:
        if event.sender.name:
            conversation.visitor_name = event.sender.name
        return conversation
    await require_capacity(session, tenant_id=event.tenant_id, resource="conversations")
    conversation = Conversation(
        tenant_id=event.tenant_id,
        workspace_id=agent.workspace_id,
        agent_id=agent.id,
        visitor_id=visitor_id,
        visitor_name=event.sender.name or "Messaging customer",
        visitor_email=event.sender.email,
        channel=_conversation_channel(event.provider),
        state=ConversationState.OPEN,
    )
    session.add(conversation)
    await session.flush()
    return conversation


async def _get_or_create_education_conversation(
    session: AsyncSession,
    *,
    event: CanonicalInboundEvent,
    agent: Agent,
    decision: EducationAccessDecision,
) -> Conversation:
    if (
        decision.student_id is None
        or decision.enrollment_id is None
        or decision.course_id is None
        or decision.batch_id is None
    ):
        raise ValueError("authorized Education decision is missing conversation scope")

    visitor_id = _visitor_key(event)
    conversation = await session.scalar(
        select(Conversation)
        .join(
            EducationConversationContext,
            EducationConversationContext.conversation_id == Conversation.id,
        )
        .where(
            Conversation.tenant_id == event.tenant_id,
            Conversation.workspace_id == agent.workspace_id,
            Conversation.agent_id == agent.id,
            Conversation.visitor_id == visitor_id,
            Conversation.state == ConversationState.OPEN,
            EducationConversationContext.tenant_id == event.tenant_id,
            EducationConversationContext.workspace_id == agent.workspace_id,
            EducationConversationContext.agent_id == agent.id,
            EducationConversationContext.student_id == decision.student_id,
            EducationConversationContext.enrollment_id == decision.enrollment_id,
            EducationConversationContext.course_id == decision.course_id,
            EducationConversationContext.batch_id == decision.batch_id,
        )
        .order_by(Conversation.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    if conversation:
        if event.sender.name:
            conversation.visitor_name = event.sender.name
        return conversation

    await require_capacity(session, tenant_id=event.tenant_id, resource="conversations")
    conversation = Conversation(
        tenant_id=event.tenant_id,
        workspace_id=agent.workspace_id,
        agent_id=agent.id,
        visitor_id=visitor_id,
        visitor_name=event.sender.name or "Messaging student",
        visitor_email=event.sender.email,
        channel=_conversation_channel(event.provider),
        state=ConversationState.OPEN,
    )
    session.add(conversation)
    await session.flush()
    session.add(
        EducationConversationContext(
            tenant_id=event.tenant_id,
            workspace_id=agent.workspace_id,
            conversation_id=conversation.id,
            agent_id=agent.id,
            student_id=decision.student_id,
            enrollment_id=decision.enrollment_id,
            course_id=decision.course_id,
            batch_id=decision.batch_id,
        )
    )
    await session.flush()
    return conversation


async def _persist_message(
    session: AsyncSession,
    *,
    event: CanonicalInboundEvent,
    conversation: Conversation,
) -> None:
    if event.message is None or event.message.text is None:
        return
    idempotency = (
        f"channel:{event.provider.value}:{event.connection_key}:"
        f"{event.message.external_message_id or event.external_event_id}"
    )[:128]
    existing = await session.scalar(
        select(Message.id).where(
            Message.tenant_id == event.tenant_id,
            Message.workspace_id == conversation.workspace_id,
            Message.idempotency_key == idempotency,
        )
    )
    if existing:
        return
    conversation.updated_at = datetime.now(UTC)
    conversation.unread_count = (conversation.unread_count or 0) + 1
    if event.sender.name:
        conversation.visitor_name = event.sender.name
    await notify_workspace_admins(
        session,
        tenant_id=event.tenant_id,
        workspace_id=conversation.workspace_id,
        title="New conversation message",
        body="A new message arrived in your workspace inbox.",
        dedupe_key=f"message:{idempotency}",
        category="conversation",
        action_url=f"/conversations?selected={conversation.id}",
        action_label="View conversations",
    )
    next_sequence = (
        int(
            await session.scalar(
                select(func.coalesce(func.max(Message.sequence), 0)).where(
                    Message.tenant_id == event.tenant_id,
                    Message.workspace_id == conversation.workspace_id,
                    Message.conversation_id == conversation.id,
                )
            )
            or 0
        )
        + 1
    )
    session.add(
        Message(
            tenant_id=event.tenant_id,
            workspace_id=conversation.workspace_id,
            conversation_id=conversation.id,
            sequence=next_sequence,
            role=MessageRole.USER,
            content=event.message.text,
            idempotency_key=idempotency,
        )
    )


async def _queue_education_setup_notice(
    session: AsyncSession,
    *,
    connection: ChannelConnection,
    event: CanonicalInboundEvent,
    conversation: Conversation,
    notice: str = EDUCATION_SETUP_NOTICE,
    reply_markup: dict | None = None,
) -> None:
    await _persist_message(session, event=event, conversation=conversation)
    await session.flush()
    sequence = int(
        await session.scalar(
            select(func.coalesce(func.max(Message.sequence), 0)).where(
                Message.tenant_id == event.tenant_id,
                Message.workspace_id == conversation.workspace_id,
                Message.conversation_id == conversation.id,
            )
        )
        or 0
    )
    reply = Message(
        tenant_id=event.tenant_id,
        workspace_id=conversation.workspace_id,
        conversation_id=conversation.id,
        sequence=sequence + 1,
        role=MessageRole.ASSISTANT,
        content=notice,
        finish_reason="stop",
    )
    session.add(reply)
    await session.flush()
    await _queue_telegram_reply(
        session,
        connection=connection,
        event=event,
        prepared=PreparedChat(conversation.id, reply.id, reply.content, []),
        reply_markup=reply_markup,
    )


async def _canonical_event(
    session: AsyncSession,
    *,
    raw: RawWebhookEvent,
    connection: ChannelConnection,
) -> CanonicalInboundEvent | None:
    if not connection.credentials_encrypted:
        credentials = {}
    else:
        try:
            credentials = credential_store.decrypt(connection.credentials_encrypted)
        except CredentialStoreError as exc:
            raise ValueError("channel credentials are unreadable") from exc
    provider = ChannelProvider(connection.provider)
    connector = channel_registry.get(provider)
    values = await connector.normalize(
        ChannelConnectionContext(
            tenant_id=raw.tenant_id,
            connection_id=connection.id,
            provider=provider,
            configuration=connection.configuration_json,
            credentials=credentials,
        ),
        payload=raw.payload_json,
        correlation_id=raw.correlation_id,
        received_at=raw.received_at,
        raw_event_id=raw.id,
    )
    return next((item for item in values if item.external_event_id == raw.external_event_id), None)


async def _process_education_message(
    session: AsyncSession,
    *,
    raw: RawWebhookEvent,
    connection: ChannelConnection,
    canonical: CanonicalInboundEvent,
    agent: Agent,
) -> None:
    channel_scope = await session.scalar(
        select(WorkspaceChannelConnection).where(
            WorkspaceChannelConnection.tenant_id == canonical.tenant_id,
            WorkspaceChannelConnection.connection_id == connection.id,
        )
    )
    if (
        channel_scope is None
        or channel_scope.workspace_id != agent.workspace_id
        or (channel_scope.agent_id is not None and channel_scope.agent_id != agent.id)
    ):
        decision = EducationAccessDecision(
            authorized=False,
            reason=EducationAccessReason.CHANNEL_SCOPE_MISMATCH,
            agent_id=agent.id,
            workspace_id=agent.workspace_id,
        )
    else:
        if canonical.provider is ChannelProvider.TELEGRAM:
            from northstar_api.services.telegram_enrollment import telegram_enrollment_notice
            notice = await telegram_enrollment_notice(session, event=canonical, agent=agent)
            if notice:
                conversation = await _get_or_create_conversation(session, event=canonical, agent=agent)
                # A contact share is identity verification, never an LLM prompt.
                await _queue_education_setup_notice(session, connection=connection, event=canonical,
                    conversation=conversation, notice=notice[0], reply_markup=notice[1])
                raw.processing_status = "processed"
                raw.processed_at = datetime.now(UTC)
                raw.attempt_count += 1
                await session.commit()
                return
        identity, mapping_reason = identity_candidate_for_event(
            canonical,
            allow_unsigned_widget=bool(connection.configuration_json.get("allowUnsigned", False)),
        )
        if identity is None:
            decision = EducationAccessDecision(
                authorized=False,
                reason=mapping_reason or EducationAccessReason.IDENTITY_MISSING,
                agent_id=agent.id,
                workspace_id=agent.workspace_id,
            )
        else:
            decision = await authorize_education_access(
                session,
                tenant_id=canonical.tenant_id,
                workspace_id=agent.workspace_id,
                agent=agent,
                identity=identity,
                message=canonical.message.text if canonical.message else None,
            )

    conversation: Conversation | None = None
    if decision.authorized:
        conversation = await _get_or_create_education_conversation(
            session,
            event=canonical,
            agent=agent,
            decision=decision,
        )
        if (
            canonical.provider is ChannelProvider.TELEGRAM
            and canonical.message is not None
            and canonical.message.text
        ):
            try:
                prepared = await education_chat_coordinator.prepare(
                    session,
                    tenant_id=canonical.tenant_id,
                    workspace_id=agent.workspace_id,
                    request=ChatStreamRequest(
                        agent_id=agent.id,
                        message=canonical.message.text,
                        conversation_id=conversation.id,
                        visitor_id=_visitor_key(canonical),
                        idempotency_key=_message_idempotency_key(canonical),
                    ),
                    channel=Channel.TELEGRAM,
                )
            except HTTPException as exc:
                if exc.status_code != 403 or exc.detail != EDUCATION_COURSE_SETUP_REQUIRED:
                    raise
                await _queue_education_setup_notice(
                    session,
                    connection=connection,
                    event=canonical,
                    conversation=conversation,
                )
            else:
                await _queue_telegram_reply(
                    session,
                    connection=connection,
                    event=canonical,
                    prepared=prepared,
                )
        else:
            await _persist_message(session, event=canonical, conversation=conversation)

    access_payload = {
        **decision.event_payload(),
        "rawEventId": str(raw.id),
        "provider": canonical.provider.value,
        "conversationId": str(conversation.id) if conversation else None,
    }
    enqueue_event(
        session,
        tenant_id=canonical.tenant_id,
        aggregate_type="education_enrollment" if decision.enrollment_id else "agent",
        aggregate_id=decision.enrollment_id or agent.id,
        event_type=(
            "education.access.authorized.v1" if decision.authorized else "education.access.denied.v1"
        ),
        payload=access_payload,
    )

    raw.processing_status = "processed"
    raw.processed_at = datetime.now(UTC)
    raw.attempt_count += 1
    enqueue_event(
        session,
        tenant_id=canonical.tenant_id,
        aggregate_type="raw_webhook_event",
        aggregate_id=raw.id,
        event_type="channel.event.processed.v1",
        payload={
            "rawEventId": str(raw.id),
            "provider": canonical.provider.value,
            "leadId": None,
            "conversationId": str(conversation.id) if conversation else None,
            "educationAccess": decision.event_payload(),
        },
    )
    await session.commit()


async def _reject_for_entitlement(
    session: AsyncSession,
    *,
    raw: RawWebhookEvent,
    provider: str,
    exc: EntitlementError,
) -> None:
    raw.processing_status = "rejected"
    raw.processed_at = datetime.now(UTC)
    raw.attempt_count += 1
    raw.last_error = f"plan entitlement: {exc.code}"[:500]
    enqueue_event(
        session,
        tenant_id=raw.tenant_id,
        aggregate_type="raw_webhook_event",
        aggregate_id=raw.id,
        event_type="channel.event.processed.v1",
        payload={
            "rawEventId": str(raw.id),
            "provider": provider,
            "leadId": None,
            "entitlementDenied": exc.code,
        },
    )
    await session.commit()
    logger.info(
        "channel_plan_entitlement_rejected",
        tenant_id=str(raw.tenant_id),
        raw_event_id=str(raw.id),
        provider=provider,
        code=exc.code,
    )


async def _process_event(session: AsyncSession, event: EventEnvelope) -> None:
    inserted = await session.scalar(
        pg_insert(ProcessedEvent)
        .values(event_id=event.event_id, consumer=CONSUMER_NAME)
        .on_conflict_do_nothing(index_elements=[ProcessedEvent.event_id, ProcessedEvent.consumer])
        .returning(ProcessedEvent.event_id)
    )
    if inserted is None:
        await session.commit()
        return
    await set_tenant_context(session, event.tenant_id)
    raw_id = _raw_event_id(event)
    raw = await session.scalar(
        select(RawWebhookEvent).where(
            RawWebhookEvent.id == raw_id,
            RawWebhookEvent.tenant_id == event.tenant_id,
        )
    )
    if not raw:
        raise ValueError("raw channel event no longer exists")
    try:
        connection_id = UUID(raw.connection_key)
    except ValueError as exc:
        raise ValueError("raw channel event has invalid connection key") from exc
    connection = await session.scalar(
        select(ChannelConnection).where(
            ChannelConnection.id == connection_id,
            ChannelConnection.tenant_id == event.tenant_id,
            ChannelConnection.status != "disabled",
        )
    )
    if not connection:
        raise ValueError("channel connection is unavailable")
    canonical = await _canonical_event(session, raw=raw, connection=connection)
    if canonical is None or canonical.event_type != "message.received":
        raw.processing_status = "ignored"
        raw.processed_at = datetime.now(UTC)
        await session.commit()
        return

    try:
        await require_channel(
            session,
            tenant_id=event.tenant_id,
            provider=canonical.provider.value,
        )
    except EntitlementError as exc:
        await _reject_for_entitlement(
            session,
            raw=raw,
            provider=canonical.provider.value,
            exc=exc,
        )
        return

    raw_agent_id = connection.configuration_json.get("agentId")
    try:
        agent_id = UUID(str(raw_agent_id))
    except (TypeError, ValueError) as exc:
        connection.status = "configuration_error"
        connection.last_error = "Channel connection must configure a valid agentId"
        raw.processing_status = "failed"
        raw.last_error = "agent_not_configured"
        await session.commit()
        raise ValueError("channel connection has no valid agentId") from exc
    agent = await session.scalar(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.tenant_id == event.tenant_id,
        )
    )
    if not agent:
        raise ValueError("channel connection agent does not exist in tenant scope")
    if agent.deleted_at is not None:
        raw.processing_status = "processed"
        raw.processed_at = datetime.now(UTC)
        raw.last_error = "agent_deleted"
        await session.commit()
        return

    purpose = await get_agent_purpose(
        session,
        tenant_id=event.tenant_id,
        workspace_id=agent.workspace_id,
        agent_id=agent.id,
    )
    try:
        if purpose is AgentPurpose.EDUCATION:
            await _process_education_message(
                session,
                raw=raw,
                connection=connection,
                canonical=canonical,
                agent=agent,
            )
            return

        conversation = await _get_or_create_conversation(session, event=canonical, agent=agent)
    except EntitlementError as exc:
        await _reject_for_entitlement(
            session,
            raw=raw,
            provider=canonical.provider.value,
            exc=exc,
        )
        return

    if (
        canonical.provider is ChannelProvider.TELEGRAM
        and agent.status is AgentStatus.ACTIVE
        and canonical.message is not None
        and canonical.message.text
    ):
        prepared = await education_chat_coordinator.prepare(
            session,
            tenant_id=canonical.tenant_id,
            workspace_id=agent.workspace_id,
            request=ChatStreamRequest(
                agent_id=agent.id,
                message=canonical.message.text,
                conversation_id=conversation.id,
                visitor_id=_visitor_key(canonical),
                idempotency_key=_message_idempotency_key(canonical),
            ),
            channel=Channel.TELEGRAM,
        )
        await _queue_telegram_reply(
            session,
            connection=connection,
            event=canonical,
            prepared=prepared,
        )
    else:
        await _persist_message(session, event=canonical, conversation=conversation)
    contact = await lead_domain_service.identity.resolve_or_create_contact(
        session,
        tenant_id=event.tenant_id,
        name=canonical.sender.name,
        email=canonical.sender.email,
        phone=canonical.sender.phone,
        provider=canonical.provider.value,
        provider_external_id=canonical.sender.external_id,
    )
    decision = await lead_qualification_engine.decide(
        session,
        tenant_id=event.tenant_id,
        event=canonical,
        fallback=dict(connection.configuration_json.get("leadCaptureDefault") or {}),
    )
    profile = await session.scalar(
        select(LeadProfile)
        .where(
            LeadProfile.tenant_id == event.tenant_id,
            LeadProfile.contact_id == contact.id,
        )
        .order_by(LeadProfile.created_at.desc())
        .limit(1)
    )
    lead: Lead | None = None
    if profile:
        lead = await session.scalar(
            select(Lead).where(
                Lead.id == profile.lead_id,
                Lead.tenant_id == event.tenant_id,
                Lead.workspace_id == agent.workspace_id,
                ~education_source(Lead),
            )
        )
    if lead is None and decision.create_lead:
        lead = Lead(
            tenant_id=event.tenant_id,
            workspace_id=agent.workspace_id,
            agent_id=agent.id,
            conversation_id=conversation.id,
            name=canonical.sender.name,
            email=canonical.sender.email,
            phone=canonical.sender.phone,
            status=LeadLifecycleStatus.NEW.value,
            consent=False,
            fields_json={"channelMetadata": canonical.metadata},
        )
        session.add(lead)
        await session.flush()
        profile = await lead_domain_service.ensure_profile(
            session,
            lead=lead,
            source_channel=canonical.provider.value,
            source_provider=canonical.provider.value,
            source_connection_id=str(connection.id),
            source_external_id=canonical.sender.external_id,
        )
        if profile.contact_id != contact.id:
            profile.contact_id = contact.id
        if canonical.campaign_attribution:
            profile.campaign = (
                str(
                    canonical.campaign_attribution.get("name")
                    or canonical.campaign_attribution.get("campaign")
                    or ""
                )
                or None
            )
        enqueue_event(
            session,
            tenant_id=event.tenant_id,
            aggregate_type="lead",
            aggregate_id=lead.id,
            event_type="lead.created.v1",
            payload={"leadId": str(lead.id), "agentId": str(agent.id), "source": canonical.provider.value},
        )
    elif lead is not None and profile is not None:
        lead.conversation_id = lead.conversation_id or conversation.id
        lead.name = lead.name or canonical.sender.name
        lead.email = lead.email or canonical.sender.email
        lead.phone = lead.phone or canonical.sender.phone
        profile.last_touch_at = canonical.received_at
        profile.source_channel = profile.source_channel or canonical.provider.value
        profile.source_provider = profile.source_provider or canonical.provider.value
        profile.source_connection_id = profile.source_connection_id or str(connection.id)
        profile.source_external_id = profile.source_external_id or canonical.sender.external_id

    if lead is not None and profile is not None and decision.qualify:
        if decision.sync_to_crm:
            await lead_domain_service.qualify(
                session,
                lead=lead,
                score=decision.score,
                reason=decision.reason,
                actor_id=None,
                correlation_id=canonical.correlation_id,
            )
        else:
            profile.lifecycle_status = LeadLifecycleStatus.QUALIFIED.value
            profile.qualification_status = QualificationStatus.QUALIFIED.value
            profile.qualification_score = decision.score
            profile.qualification_reason = decision.reason
            profile.qualified_at = datetime.now(UTC)
            lead.status = LeadLifecycleStatus.QUALIFIED.value
            session.add(
                LeadActivityEvent(
                    tenant_id=event.tenant_id,
                    lead_id=lead.id,
                    event_type="lead.qualified.v1",
                    correlation_id=canonical.correlation_id,
                    details_json={"score": decision.score, "reason": decision.reason},
                )
            )
            enqueue_event(
                session,
                tenant_id=event.tenant_id,
                aggregate_type="lead",
                aggregate_id=lead.id,
                event_type="lead.qualified.v1",
                payload={"leadId": str(lead.id), "score": decision.score},
            )
    elif lead is not None and decision.sync_to_crm:
        await lead_domain_service.request_sync(
            session,
            lead=lead,
            reason=decision.reason,
            correlation_id=canonical.correlation_id,
        )

    raw.processing_status = "processed"
    raw.processed_at = datetime.now(UTC)
    raw.attempt_count += 1
    enqueue_event(
        session,
        tenant_id=event.tenant_id,
        aggregate_type="raw_webhook_event",
        aggregate_id=raw.id,
        event_type="channel.event.processed.v1",
        payload={
            "rawEventId": str(raw.id),
            "provider": canonical.provider.value,
            "leadId": str(lead.id) if lead else None,
        },
    )
    await session.commit()


async def consume_forever() -> None:
    engine = build_engine(settings)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    consumer = AIOKafkaConsumer(
        *TOPICS,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=CONSUMER_NAME,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
        client_id="northstar-channel-lead-router",
    )
    await consumer.start()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signal_name, stop.set)
        except NotImplementedError:
            pass
    logger.info("channel_event_consumer_started")
    try:
        while not stop.is_set():
            batch = await consumer.getmany(timeout_ms=1000, max_records=1)
            for messages in batch.values():
                for message in messages:
                    tp = TopicPartition(message.topic, message.partition)
                    raw_bytes = message.value if isinstance(message.value, bytes) else b""
                    try:
                        envelope = parse_envelope(raw_bytes)
                        if envelope.event_type != message.topic:
                            raise ValueError("event type does not match Kafka topic")
                        _raw_event_id(envelope)
                    except ValueError as exc:
                        async with factory() as session:
                            await quarantine_event(
                                session,
                                consumer=CONSUMER_NAME,
                                topic=message.topic,
                                partition=message.partition,
                                offset=message.offset,
                                raw=raw_bytes,
                                error=exc,
                            )
                        await consumer.commit({tp: message.offset + 1})
                        continue
                    try:
                        async with factory() as session:
                            await _process_event(session, envelope)
                        await consumer.commit({tp: message.offset + 1})
                    except Exception as exc:
                        logger.warning(
                            "channel_event_retry",
                            event_id=str(envelope.event_id),
                            error=type(exc).__name__,
                        )
                        consumer.seek(tp, message.offset)
                        try:
                            await asyncio.wait_for(stop.wait(), timeout=1.0)
                        except TimeoutError:
                            pass
                        break  # Do not advance past a failed partition offset.
    finally:
        await consumer.stop()
        await engine.dispose()
        logger.info("channel_event_consumer_stopped")


def main() -> None:
    if not settings.kafka_enabled:
        raise SystemExit("KAFKA_ENABLED must be true for the channel event consumer")
    asyncio.run(consume_forever())


if __name__ == "__main__":
    main()
