from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.config import get_settings
from northstar_api.metrics import CHAT_DURATION, CHAT_REQUESTS
from northstar_api.models import (
    Agent,
    Channel,
    Conversation,
    KnowledgeAnswerAudit,
    KnowledgeSnapshot,
    Message,
    MessageCitation,
    MessageRole,
    Workspace,
)
from northstar_api.modules.knowledge.grounding import blocked_topic, validate_answer
from northstar_api.modules.knowledge.retrieval import Evidence, RetrievalService, retrieval_service
from northstar_api.modules.whatsapp.messages import format_whatsapp_reply
from northstar_api.schemas import ChatStreamRequest
from northstar_api.services.bot_workflows import match_bot_workflow
from northstar_api.services.llm import (
    ModelUnavailableError,
    NvidiaModelAdapter,
    nvidia_adapter,
    runtime_model_profile,
)
from northstar_api.services.localization import (
    localized_appearance,
    localized_no_evidence,
    localized_provider_fallback,
    localized_question_fallback,
)
from northstar_api.services.notifications import notify_workspace_admins
from northstar_api.services.outbox import enqueue_event
from northstar_api.services.rate_limit import RedisServices, redis_services
from northstar_api.services.redaction import mask_sensitive_text
from northstar_api.services.web_fallback import related_web_evidence, selected_web_fallback

FAILED_RESPONSE_PLACEHOLDER = "The assistant could not complete this response."


def whatsapp_welcome(agent: Agent, message: str) -> str | None:
    """Answer greeting-only messages from configured copy, after access checks."""
    settings = (agent.appearance or {}).get("whatsapp") or {}
    if settings.get("welcomeEnabled") is False:
        return None
    greeting = re.sub(r"[!?.,\s👋]+", " ", message.casefold()).strip()
    if greeting not in {"hi", "hii", "hiii", "hello", "hey", "good morning", "good afternoon", "good evening", "namaste", "नमस्ते", "नमस्कार", "hola", "bonjour", "hallo", "مرحبا", "السلام عليكم"}:
        return None
    if settings.get("welcomeMessage"):
        return str(settings["welcomeMessage"]).strip()
    locale = localized_appearance(agent.language)
    body = str((agent.appearance or {}).get("welcomeMessage") or locale["welcomeMessage"]).strip()
    heading = f"Hi! Welcome to {agent.name}." if agent.language == "English" else f"{agent.name}\n{locale['welcomeTitle']}"
    return f"{heading}\n\n{body}"


@dataclass(frozen=True, slots=True)
class PreparedChat:
    conversation_id: UUID
    assistant_message_id: UUID
    answer: str
    evidence: list[Evidence]
    display_question: str = ""
    message_format: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ReservedChat:
    conversation_id: UUID
    assistant_message_id: UUID
    assistant_sequence: int
    lease_id: str


class ChatCoordinator:
    def __init__(
        self,
        retrieval: RetrievalService | None = None,
        model: NvidiaModelAdapter | None = None,
        redis: RedisServices | None = None,
    ) -> None:
        self.retrieval = retrieval or retrieval_service
        self.model = model or nvidia_adapter
        self.redis = redis or redis_services

    async def prepare(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        workspace_id: UUID | None = None,
        allowed_agent_ids: frozenset[UUID] | None = None,
        request: ChatStreamRequest,
        channel: Channel = Channel.WIDGET,
    ) -> PreparedChat:
        started = time.perf_counter()
        agent = await self._get_agent(
            session,
            tenant_id,
            request.agent_id,
            workspace_id=workspace_id,
            allowed_agent_ids=allowed_agent_ids,
        )
        raw_message = request.message.strip()
        message_fingerprint = hashlib.sha256(raw_message.encode("utf-8")).hexdigest()
        workspace_settings = await session.scalar(
            select(Workspace.settings_json).where(
                Workspace.id == agent.workspace_id,
                Workspace.tenant_id == tenant_id,
            )
        )
        workspace_security = dict((workspace_settings or {}).get("security", {}))
        workspace_masking = workspace_security.get("sensitiveDataMasking", True) is not False
        message = (
            mask_sensitive_text(raw_message)
            if workspace_masking and agent.security.get("maskSensitiveData", True)
            else raw_message
        )
        blocked = blocked_topic(raw_message, (agent.security or {}).get("blockedTopics", []))
        if blocked:
            raise HTTPException(status_code=422, detail=f"This agent does not answer questions about {blocked}.")
        rate_limit = int(agent.security.get("rateLimitPerMinute", 30))
        global_limiter = await self.redis.check_rate_limit(
            f"tenant:{tenant_id}:agent:{agent.id}:global",
            get_settings().agent_global_rate_limit_per_minute,
            scope="chat_global",
        )
        if not global_limiter.allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Agent message capacity exceeded",
                headers={"Retry-After": str(global_limiter.retry_after)},
            )
        limiter = await self.redis.check_rate_limit(
            f"tenant:{tenant_id}:agent:{agent.id}:visitor:{request.visitor_id or 'admin'}", rate_limit
        )
        if not limiter.allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Message rate limit exceeded",
                headers={"Retry-After": str(limiter.retry_after)},
            )
        conversation = await self._get_or_create_conversation(
            session, tenant_id=tenant_id, agent=agent, request=request, channel=channel
        )
        show_citations = agent.model_profile.get("citationMode", "when-available") != "off"
        reservation = await self._reserve_exchange(
            session,
            tenant_id=tenant_id,
            agent=agent,
            conversation=conversation,
            request=request,
            message=message,
            message_fingerprint=message_fingerprint,
            show_citations=show_citations,
        )
        configured_greeting = whatsapp_welcome(agent, raw_message)
        welcome = configured_greeting if channel in {Channel.WHATSAPP, Channel.TELEGRAM} else None
        display_question = raw_message if welcome else await self._display_question(agent, raw_message)
        if isinstance(reservation, PreparedChat):
            return replace(reservation, display_question=display_question)
        try:
            workflow_reply = await match_bot_workflow(
                session,
                tenant_id=tenant_id,
                workspace_id=agent.workspace_id,
                agent_id=agent.id,
                conversation_id=reservation.conversation_id,
                message=raw_message,
                channel=channel.value,
                include_fallback=False,
            )
            if workflow_reply:
                prepared = await self._complete_exchange(
                    session, tenant_id=tenant_id, agent=agent, reservation=reservation,
                    question=message, answer=workflow_reply.content, evidence=[],
                    latency_ms=round((time.perf_counter() - started) * 1000), show_citations=False,
                    message_format=workflow_reply.message_format,
                    answer_mode="workflow",
                )
                CHAT_REQUESTS.labels("workflow").inc()
                CHAT_DURATION.observe(time.perf_counter() - started)
                return replace(prepared, display_question=display_question)
            if welcome:
                prepared = await self._complete_exchange(
                    session, tenant_id=tenant_id, agent=agent, reservation=reservation,
                    question=message, answer=welcome, evidence=[],
                    latency_ms=round((time.perf_counter() - started) * 1000), show_citations=False,
                    answer_mode="welcome",
                )
                CHAT_REQUESTS.labels("welcome").inc()
                CHAT_DURATION.observe(time.perf_counter() - started)
                return replace(prepared, display_question=display_question)
            conversation_history = await self._recent_history(session, reservation)
            retrieval_query = _retrieval_query(message, conversation_history)
            try:
                evidence = await self.retrieval.retrieve(
                    session,
                    tenant_id=tenant_id,
                    agent_id=agent.id,
                    revision=conversation.knowledge_revision,
                    query=retrieval_query,
                    rerank_candidates=int((agent.model_profile or {}).get("rerankCandidates", 60)),
                    final_context_chunks=int((agent.model_profile or {}).get("finalContextChunks", 8)),
                )
            except ModelUnavailableError:
                await session.rollback()
                raise HTTPException(
                    status_code=503, detail="AI retrieval is temporarily unavailable"
                ) from None
            # Retrieval is read-only; release its transaction before provider I/O.
            await session.commit()
            web_evidence = False
            answer_mode = "abstained"
            # Every Support and Lead-generation answer starts with the same
            # vectorless lexical retrieval. The saved dropdown controls only
            # what may happen after that approved knowledge has no evidence.
            web_policy = selected_web_fallback(agent.security)
            configured_internet = str((agent.model_profile or {}).get("internetAccess", ""))
            if configured_internet in {"none", "allowlisted", "public"}:
                web_policy = {"none": "off", "allowlisted": "related_only", "public": "public"}[configured_internet]
            if not evidence and configured_greeting is None and web_policy in {"related_only", "public"}:
                evidence = await related_web_evidence(
                    retrieval_query,
                    list((agent.security or {}).get("webAllowedDomains", [])),
                    allow_public=web_policy == "public",
                )
                web_evidence = bool(evidence)
            if not evidence:
                workflow_reply = await match_bot_workflow(
                    session,
                    tenant_id=tenant_id,
                    workspace_id=agent.workspace_id,
                    agent_id=agent.id,
                    conversation_id=reservation.conversation_id,
                    message=raw_message,
                    channel=channel.value,
                )
                if workflow_reply:
                    prepared = await self._complete_exchange(
                        session, tenant_id=tenant_id, agent=agent, reservation=reservation,
                        question=message, answer=workflow_reply.content, evidence=[],
                        latency_ms=round((time.perf_counter() - started) * 1000), show_citations=False,
                        message_format=workflow_reply.message_format,
                        answer_mode="workflow",
                    )
                    CHAT_REQUESTS.labels("workflow").inc()
                    CHAT_DURATION.observe(time.perf_counter() - started)
                    return replace(prepared, display_question=display_question)
                if web_policy == "public":
                    try:
                        runtime_profile = await runtime_model_profile(session, agent)
                    except ModelUnavailableError:
                        raise HTTPException(
                            status_code=503,
                            detail="The selected AI provider connection is unavailable",
                        ) from None
                    answer = await self._general_answer(agent, message, conversation_history, runtime_profile)
                    answer_mode = "general_assistance"
                    CHAT_REQUESTS.labels("general_knowledge").inc()
                else:
                    answer = localized_no_evidence(agent.language)
                    CHAT_REQUESTS.labels("refused_no_evidence").inc()
            else:
                answer_mode = "approved_public_evidence" if web_evidence else "approved_knowledge"
                evidence_block = "\n\n".join(
                    f"[S{index} | {item.title} | page={item.metadata.get('page_number', 'unknown')} | type={item.metadata.get('chunk_type', item.kind)}]\n{item.text}"
                    for index, item in enumerate(evidence, start=1)
                )
                try:
                    runtime_profile = await runtime_model_profile(session, agent)
                    generated = await self.model.generate_grounded(
                        instructions=agent.instructions,
                        question=message,
                        evidence=evidence_block,
                        conversation_history=conversation_history,
                        language=agent.language,
                        tone=agent.tone.value,
                        model_profile=runtime_profile,
                        allow_external_evidence=web_evidence,
                    )
                    answer = generated.content
                    grounding = validate_answer(answer, evidence)
                    if not grounding.allowed:
                        # Do not turn a valid retrieval into a false "no
                        # information" response merely because the model used
                        # wording that the deterministic post-check cannot
                        # verify.  Return the bounded, cited source excerpt;
                        # this remains strictly grounded and does not widen the
                        # answer to model knowledge.
                        answer = _evidence_fallback(evidence[0], message)
                        answer_mode = "grounded_fallback"
                        CHAT_REQUESTS.labels("grounded_fallback").inc()
                    else:
                        CHAT_REQUESTS.labels("generated").inc()
                except ModelUnavailableError:
                    # The deterministic cited fallback is development-only. Production
                    # makes an upstream failure explicit when REQUIRE_NVIDIA is enabled.
                    if self.model.settings.require_nvidia:
                        raise HTTPException(
                            status_code=503, detail="AI provider is temporarily unavailable"
                        ) from None
                    answer = (
                        _evidence_fallback(evidence[0])
                        if agent.language == "English"
                        else localized_provider_fallback(agent.language)
                    )
                    CHAT_REQUESTS.labels("grounded_fallback").inc()

            if channel == Channel.WHATSAPP:
                answer = format_whatsapp_reply(agent, answer)
            latency_ms = round((time.perf_counter() - started) * 1000)
            prepared = await self._complete_exchange(
                session,
                tenant_id=tenant_id,
                agent=agent,
                reservation=reservation,
                question=message,
                answer=answer,
                evidence=evidence,
                latency_ms=latency_ms,
                show_citations=show_citations,
                answer_mode=answer_mode,
            )
        except Exception:
            await session.rollback()
            await self._mark_reservation_failed(session, tenant_id, reservation)
            raise
        CHAT_DURATION.observe(time.perf_counter() - started)
        return replace(prepared, display_question=display_question)

    async def _display_question(self, agent: Agent, question: str) -> str:
        if agent.language == "English":
            return question
        translator = getattr(self.model, "translate_for_display", None)
        if translator is None:
            return localized_question_fallback(question, agent.language)
        try:
            translated = await translator(question, agent.language, agent.model_profile)
            return str(translated)
        except ModelUnavailableError:
            return localized_question_fallback(question, agent.language)

    async def _general_answer(self, agent: Agent, question: str, conversation_history: str, model_profile: dict[str, Any] | None = None) -> str:
        generator = getattr(self.model, "generate_general", None)
        if generator is None:
            return localized_no_evidence(agent.language)
        try:
            generated = await generator(
                instructions=agent.instructions,
                question=question,
                conversation_history=conversation_history,
                language=agent.language,
                tone=agent.tone.value,
                model_profile=model_profile or agent.model_profile,
            )
        except ModelUnavailableError:
            if getattr(getattr(self.model, "settings", None), "require_nvidia", False):
                raise
            return localized_no_evidence(agent.language)
        return str(generated.content)

    async def _reserve_exchange(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        agent: Agent,
        conversation: Conversation,
        request: ChatStreamRequest,
        message: str,
        message_fingerprint: str,
        show_citations: bool,
    ) -> ReservedChat | PreparedChat:
        locked_conversation = await session.scalar(
            select(Conversation)
            .where(
                Conversation.id == conversation.id,
                Conversation.tenant_id == tenant_id,
                Conversation.agent_id == agent.id,
            )
            .with_for_update()
        )
        if not locked_conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
        if request.idempotency_key:
            user_message = await session.scalar(
                select(Message).where(
                    Message.conversation_id == conversation.id,
                    Message.idempotency_key == request.idempotency_key,
                    Message.role == MessageRole.USER,
                )
            )
            if user_message:
                existing_fingerprint = (
                    user_message.content_fingerprint
                    or hashlib.sha256(user_message.content.encode("utf-8")).hexdigest()
                )
                if existing_fingerprint != message_fingerprint:
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency key was already used for a different message",
                    )
                assistant = await session.scalar(
                    select(Message).where(
                        Message.conversation_id == conversation.id,
                        Message.sequence == user_message.sequence + 1,
                        Message.role == MessageRole.ASSISTANT,
                    )
                )
                if not assistant:
                    raise HTTPException(
                        status_code=409, detail="An identical message is still being processed"
                    )
                if assistant.finish_reason == "stop":
                    prepared = await self._prepared_from_message(
                        session,
                        conversation.id,
                        assistant,
                        show_citations=show_citations,
                    )
                    await session.commit()
                    return prepared
                processing_started_at = assistant.processing_started_at or assistant.created_at
                if processing_started_at.tzinfo is None:
                    processing_started_at = processing_started_at.replace(tzinfo=UTC)
                lease_expired = processing_started_at < datetime.now(UTC) - timedelta(minutes=5)
                if assistant.finish_reason == "processing" and not lease_expired:
                    raise HTTPException(
                        status_code=409, detail="An identical message is still being processed"
                    )
                lease_id = uuid4().hex
                assistant.content = ""
                assistant.finish_reason = "processing"
                assistant.model_request_id = lease_id
                assistant.processing_started_at = datetime.now(UTC)
                await session.commit()
                return ReservedChat(conversation.id, assistant.id, assistant.sequence, lease_id)

        sequence = int(
            await session.scalar(
                select(func.coalesce(func.max(Message.sequence), 0)).where(
                    Message.conversation_id == conversation.id
                )
            )
            or 0
        )
        user_message = Message(
            tenant_id=tenant_id,
            workspace_id=agent.workspace_id,
            conversation_id=conversation.id,
            sequence=sequence + 1,
            role=MessageRole.USER,
            content=message,
            content_fingerprint=message_fingerprint,
            idempotency_key=request.idempotency_key,
        )
        session.add(user_message)
        await session.flush()
        locked_conversation.updated_at = datetime.now(UTC)
        locked_conversation.unread_count = (locked_conversation.unread_count or 0) + 1
        await notify_workspace_admins(
            session,
            tenant_id=tenant_id,
            workspace_id=agent.workspace_id,
            title="New conversation message",
            body="A new message arrived in your workspace inbox.",
            dedupe_key=f"message:{user_message.id}",
            category="conversation",
            action_url=f"/conversations?selected={conversation.id}",
            action_label="View conversation",
        )
        lease_id = uuid4().hex
        assistant = Message(
            tenant_id=tenant_id,
            workspace_id=agent.workspace_id,
            conversation_id=conversation.id,
            sequence=sequence + 2,
            role=MessageRole.ASSISTANT,
            content="",
            model_request_id=lease_id,
            finish_reason="processing",
            processing_started_at=datetime.now(UTC),
        )
        session.add(assistant)
        enqueue_event(
            session,
            tenant_id=tenant_id,
            aggregate_type="conversation",
            aggregate_id=conversation.id,
            event_type="chat.message.created.v1",
            payload={"conversationId": str(conversation.id), "agentId": str(agent.id), "role": "user"},
        )
        await session.flush()
        assistant_id = assistant.id
        await session.commit()
        return ReservedChat(conversation.id, assistant_id, assistant.sequence, lease_id)

    async def _recent_history(self, session: AsyncSession, reservation: ReservedChat) -> str:
        rows = (
            await session.scalars(
                select(Message)
                .where(
                    Message.conversation_id == reservation.conversation_id,
                    Message.sequence < reservation.assistant_sequence - 1,
                    or_(
                        Message.role == MessageRole.USER,
                        Message.finish_reason == "stop",
                    ),
                )
                .order_by(Message.sequence.desc())
                .limit(8)
            )
        ).all()
        ordered = list(reversed(rows))
        history = "\n".join(f"{item.role.value}: {item.content}" for item in ordered)
        return history[-6_000:]

    async def _complete_exchange(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        agent: Agent,
        reservation: ReservedChat,
        question: str,
        answer: str,
        evidence: list[Evidence],
        latency_ms: int,
        show_citations: bool,
        message_format: dict[str, Any] | None = None,
        answer_mode: str = "non_knowledge",
    ) -> PreparedChat:
        assistant = await session.scalar(
            select(Message)
            .where(
                Message.id == reservation.assistant_message_id,
                Message.tenant_id == tenant_id,
            )
            .with_for_update()
        )
        if not assistant:
            raise HTTPException(status_code=409, detail="Chat request reservation no longer exists")
        if assistant.finish_reason == "stop":
            prepared = await self._prepared_from_message(
                session,
                reservation.conversation_id,
                assistant,
                show_citations=show_citations,
            )
            await session.commit()
            return prepared
        if assistant.model_request_id != reservation.lease_id:
            raise HTTPException(status_code=409, detail="Chat request lease was superseded")
        assistant.content = answer
        assistant.content_json = message_format or {"type": "text"}
        assistant.completion_tokens = max(1, len(answer.split()))
        assistant.prompt_tokens = max(
            1, len(question.split()) + sum(len(item.text.split()) for item in evidence)
        )
        assistant.latency_ms = latency_ms
        assistant.confidence = evidence[0].score if evidence else 0.0
        assistant.finish_reason = "stop"
        assistant.processing_started_at = None
        for rank, item in enumerate(evidence, start=1):
            session.add(
                MessageCitation(
                    tenant_id=tenant_id,
                    workspace_id=agent.workspace_id,
                    message_id=assistant.id,
                    source_id=UUID(item.source_id) if item.source_id else None,
                    fact_id=UUID(item.entity_id) if item.kind == "fact" else None,
                    chunk_id=UUID(item.entity_id) if item.kind == "chunk" else None,
                    rank=rank,
                    retrieval_score=item.score,
                    title=item.title,
                    url=item.url,
                )
            )
        conversation_revision = await session.scalar(
            select(Conversation.knowledge_revision).where(
                Conversation.id == reservation.conversation_id,
                Conversation.tenant_id == tenant_id,
            )
        )
        snapshot = await session.scalar(
            select(KnowledgeSnapshot).where(
                KnowledgeSnapshot.tenant_id == tenant_id,
                KnowledgeSnapshot.agent_id == agent.id,
                KnowledgeSnapshot.revision == conversation_revision,
            )
        )
        session.add(
            KnowledgeAnswerAudit(
                tenant_id=tenant_id,
                workspace_id=agent.workspace_id,
                agent_id=agent.id,
                message_id=assistant.id,
                snapshot_id=snapshot.id if snapshot else None,
                details={
                    "answerMode": answer_mode,
                    "knowledgeRevision": conversation_revision,
                    "evidenceCount": len(evidence),
                    "sourceIds": sorted({item.source_id for item in evidence if item.source_id}),
                    "groundingAccepted": bool(evidence),
                    "policyRevision": 1,
                },
            )
        )
        enqueue_event(
            session,
            tenant_id=tenant_id,
            aggregate_type="conversation",
            aggregate_id=reservation.conversation_id,
            event_type="chat.response.completed.v1",
            payload={
                "conversationId": str(reservation.conversation_id),
                "agentId": str(agent.id),
                "messageId": str(assistant.id),
                "latencyMs": latency_ms,
                "evidenceCount": len(evidence),
                "answerable": bool(evidence),
                "conversationStarted": assistant.sequence == 2,
            },
        )
        await session.commit()
        return PreparedChat(
            reservation.conversation_id,
            assistant.id,
            answer,
            evidence if show_citations else [],
            message_format=assistant.content_json or None,
        )

    async def _get_agent(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        identifier: UUID | str,
        *,
        workspace_id: UUID | None = None,
        allowed_agent_ids: frozenset[UUID] | None = None,
    ) -> Agent:
        conditions = [Agent.public_id == str(identifier)]
        try:
            conditions.append(Agent.id == UUID(str(identifier)))
        except ValueError:
            pass
        scope = [Agent.tenant_id == tenant_id, Agent.deleted_at.is_(None), or_(*conditions)]
        if workspace_id:
            scope.append(Agent.workspace_id == workspace_id)
        if allowed_agent_ids is not None:
            scope.append(Agent.id.in_(allowed_agent_ids))
        agent = await session.scalar(select(Agent).where(*scope))
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        return agent

    async def _get_or_create_conversation(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        agent: Agent,
        request: ChatStreamRequest,
        channel: Channel,
    ) -> Conversation:
        conversation: Conversation | None = None
        idempotent_conversation: Conversation | None = None
        if request.idempotency_key:
            # Serialize the first reservation across processes. The database-level
            # uniqueness constraint remains the final guard; this lock lets a retry
            # discover the winning conversation before it attempts an insert.
            if session.bind and session.bind.dialect.name == "postgresql":
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
                    {"scope": (f"chat:{tenant_id}:{request.idempotency_key}")},
                )
            idempotent_conversation = await session.scalar(
                select(Conversation)
                .join(Message, Message.conversation_id == Conversation.id)
                .where(
                    Message.tenant_id == tenant_id,
                    Message.idempotency_key == request.idempotency_key,
                    Message.role == MessageRole.USER,
                )
            )
            if idempotent_conversation and idempotent_conversation.agent_id != agent.id:
                raise HTTPException(
                    status_code=409,
                    detail="Idempotency key was already used for another agent",
                )
        if request.conversation_id:
            conditions = [Conversation.public_id == str(request.conversation_id)]
            try:
                conditions.append(Conversation.id == UUID(str(request.conversation_id)))
            except ValueError:
                pass
            conversation = await session.scalar(
                select(Conversation).where(
                    Conversation.tenant_id == tenant_id,
                    Conversation.agent_id == agent.id,
                    or_(*conditions),
                )
            )
            if not conversation:
                raise HTTPException(status_code=404, detail="Conversation not found")
            if idempotent_conversation and idempotent_conversation.id != conversation.id:
                raise HTTPException(
                    status_code=409,
                    detail="Idempotency key was already used for another conversation",
                )
        elif idempotent_conversation:
            conversation = idempotent_conversation
        if not conversation:
            conversation = Conversation(
                tenant_id=tenant_id,
                workspace_id=agent.workspace_id,
                agent_id=agent.id,
                visitor_id=request.visitor_id,
                channel=channel,
                knowledge_revision=agent.published_knowledge_revision,
            )
            session.add(conversation)
            await session.flush()
        return conversation

    async def _prepared_from_message(
        self,
        session: AsyncSession,
        conversation_id: UUID,
        assistant: Message,
        *,
        show_citations: bool,
    ) -> PreparedChat:
        evidence: list[Evidence] = []
        if show_citations:
            citations = (
                await session.scalars(
                    select(MessageCitation)
                    .where(MessageCitation.message_id == assistant.id)
                    .order_by(MessageCitation.rank)
                )
            ).all()
            evidence = [
                Evidence(
                    kind="citation",
                    entity_id=str(citation.id),
                    source_id=str(citation.source_id) if citation.source_id else None,
                    title=citation.title,
                    url=citation.url,
                    text="",
                    score=citation.retrieval_score,
                )
                for citation in citations
            ]
        return PreparedChat(
            conversation_id, assistant.id, assistant.content, evidence,
            message_format=assistant.content_json or None,
        )

    async def _mark_reservation_failed(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        reservation: ReservedChat,
    ) -> None:
        try:
            assistant = await session.scalar(
                select(Message).where(
                    Message.id == reservation.assistant_message_id,
                    Message.tenant_id == tenant_id,
                )
            )
            if assistant and assistant.model_request_id == reservation.lease_id:
                # Failure is transport state, not an assistant answer. Keeping this
                # empty lets idempotent channel retries reacquire the reservation
                # without exposing an internal placeholder to the customer.
                assistant.content = ""
                assistant.finish_reason = "failed"
                assistant.processing_started_at = None
                await session.commit()
        except Exception:
            await session.rollback()


def _evidence_fallback(evidence: Evidence, question: str = "") -> str:
    if evidence.kind == "fact" and "\nA: " in evidence.text:
        return evidence.text.split("\nA: ", 1)[1].strip()
    # Avoid dumping an entire document into the response.
    sentences = re.split(r"(?<=[.!?])\s+", evidence.text.strip())
    if question:
        stop_words = {"a", "an", "and", "are", "from", "is", "of", "the", "to", "what", "which"}
        terms = {word for word in re.findall(r"\w+", question.casefold()) if word not in stop_words}
        if terms:
            start = max(
                range(len(sentences)),
                key=lambda index: len(terms & set(re.findall(r"\w+", sentences[index].casefold()))),
            )
            return " ".join(sentences[start : start + 3])[:1200]
    return " ".join(sentences[:3])[:1200]


def _retrieval_query(question: str, conversation_history: str) -> str:
    normalized = question.casefold()
    context_markers = re.compile(
        r"\b(it|its|that|this|those|these|they|them|their|he|she|his|her|former|latter)\b"
        r"|\b(what|how) about\b"
    )
    if not conversation_history or len(question.split()) > 24 or not context_markers.search(normalized):
        return question
    prior_user_messages = [
        line.removeprefix("user: ") for line in conversation_history.splitlines() if line.startswith("user: ")
    ]
    if not prior_user_messages:
        return question
    # Use the fully specified prior question for retrieval; the current follow-up
    # still reaches the generator, where it narrows how the retrieved facts apply.
    # Concatenating pronouns and filler into a websearch query can turn useful
    # lexical terms into an over-constrained AND expression.
    return prior_user_messages[-1]


def token_chunks(value: str) -> list[str]:
    return re.findall(r"\S+\s*", value)


chat_coordinator = ChatCoordinator()
