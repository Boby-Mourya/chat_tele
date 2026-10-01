from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Load, selectinload

from northstar_api.agent_purpose import AgentPurpose, AgentPurposeSetting
from northstar_api.services.conversation_activity import conversation_activity_order, conversation_activity_time
from northstar_api.config import get_settings
from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.lead_crm.channel_models import ChannelConnection, ChannelOutboundDelivery
from northstar_api.lead_crm.channel_scope import WorkspaceChannelConnection
from northstar_api.lead_crm.credentials import CredentialStoreError, credential_store
from northstar_api.lead_crm.domain import ChannelProvider
from northstar_api.lead_crm.services import lead_domain_service
from northstar_api.logging import request_id_ctx
from northstar_api.models import (
    Channel,
    Conversation,
    ConversationState,
    Message,
    MessageRole,
    WhatsAppConnection,
    WhatsAppInboundMessage,
    WhatsAppOutboundDelivery,
)
from northstar_api.modules.whatsapp.accounts import connection_client
from northstar_api.modules.whatsapp.graph import (
    WhatsAppConfigurationError,
    WhatsAppGraphError,
    token_expiry_is_current,
)
from northstar_api.modules.whatsapp.status import attach_whatsapp_message_status
from northstar_api.modules.whatsapp.templates import build_template
from northstar_api.schemas import (
    CitationOut,
    ConversationOut,
    ConversationPatch,
    ConversationReplyCreate,
    ConversationResolve,
    MessageOut,
    PageResult,
)
from northstar_api.security import Principal
from northstar_api.services.conversation_lead_status import attach_lead_status
from northstar_api.services.conversation_resolution import conversation_resolution_service
from northstar_api.services.education_conversation_policy import (
    EDUCATION_WORKFLOW_MESSAGE,
    conversation_purpose,
    education_source,
)
from northstar_api.services.outbox import enqueue_event
from northstar_api.services.slack import decode_slack_target
from northstar_api.workers.facebook_messenger_tasks import send_facebook_messenger_message
from northstar_api.workers.instagram_tasks import send_instagram_message
from northstar_api.workers.slack_tasks import send_slack_message
from northstar_api.workers.tasks import send_whatsapp_human_reply
from northstar_api.workers.telegram_tasks import send_telegram_message

router = APIRouter(prefix="/conversations", tags=["conversations"])
DB = Annotated[AsyncSession, Depends(get_session)]
ConversationsViewPrincipal = Annotated[Principal, Depends(require_permissions("conversations.view"))]
ConversationsResolvePrincipal = Annotated[Principal, Depends(require_permissions("conversations.resolve"))]
ConversationsReplyPrincipal = Annotated[Principal, Depends(require_permissions("conversations.reply"))]


def conversation_response(conversation: Conversation) -> ConversationOut:
    messages = [
        MessageOut(
            id=message.id,
            role=message.role,
            content=message.content,
            created_at=message.created_at,
            citations=[CitationOut(title=item.title, url=item.url) for item in message.citations],
            message_format=message.content_json or None,
        )
        for message in conversation.messages
    ]
    preview = messages[-1].content[:240] if messages else "No messages yet"
    return ConversationOut(
        id=conversation.id,
        workspace_id=conversation.workspace_id,
        agent_id=conversation.agent_id,
        visitor_name=conversation.visitor_name,
        visitor_email=conversation.visitor_email,
        page_url=conversation.page_url,
        visitor_details=conversation.visitor_details or {},
        channel=conversation.channel,
        state=conversation.state,
        sentiment=conversation.sentiment,
        preview=preview,
        unread=conversation.unread_count,
        started_at=conversation.started_at,
        updated_at=conversation_activity_time(conversation),
        messages=messages,
    )


def conversation_options() -> Load:
    # SQLAlchemy's public type hint is the abstract loader base, while this
    # factory returns a concrete Load instance at runtime.
    return cast(Load, selectinload(Conversation.messages).selectinload(Message.citations))


def conversation_scope(principal: Principal, conversation_id: UUID) -> tuple[object, ...]:
    return (
        Conversation.id == conversation_id,
        Conversation.tenant_id == principal.tenant_id,
        Conversation.workspace_id == principal.workspace_id,
        *((Conversation.agent_id.in_(principal.agent_ids),) if principal.agent_ids is not None else ()),
    )


async def locked_conversation(
    session: AsyncSession,
    principal: Principal,
    conversation_id: UUID,
) -> Conversation | None:
    return await session.scalar(
        select(Conversation)
        .options(conversation_options())
        .where(*conversation_scope(principal, conversation_id))
        .with_for_update()
    )


def _telegram_chat_id(conversation: Conversation) -> str | None:
    visitor_id = conversation.visitor_id or ""
    if not visitor_id.startswith("telegram:"):
        return None
    chat_id = visitor_id.removeprefix("telegram:").strip()
    if not chat_id or not chat_id.lstrip("-").isdigit():
        return None
    return chat_id


def _instagram_recipient_id(conversation: Conversation) -> str | None:
    visitor_id = conversation.visitor_id or ""
    if not visitor_id.startswith("instagram:"):
        return None
    recipient_id = visitor_id.removeprefix("instagram:").strip()
    if not recipient_id or not recipient_id.isdigit():
        return None
    return recipient_id


def _facebook_messenger_recipient_id(conversation: Conversation) -> str | None:
    visitor_id = conversation.visitor_id or ""
    if not visitor_id.startswith("facebook_messenger:"):
        return None
    recipient_id = visitor_id.removeprefix("facebook_messenger:").strip()
    if not recipient_id or not recipient_id.isdigit():
        return None
    return recipient_id


def _slack_delivery_target(conversation: Conversation) -> str | None:
    visitor_id = conversation.visitor_id or ""
    if conversation.channel != Channel.SLACK or not visitor_id.startswith("slack:"):
        return None
    target = visitor_id.removeprefix("slack:").strip()
    return target if decode_slack_target(target) is not None else None


async def _telegram_connection_for_conversation(
    session: AsyncSession,
    principal: Principal,
    conversation: Conversation,
) -> tuple[ChannelConnection, str] | None:
    chat_id = _telegram_chat_id(conversation)
    if chat_id is None:
        return None
    rows = (
        await session.execute(
            select(ChannelConnection, WorkspaceChannelConnection)
            .join(
                WorkspaceChannelConnection,
                WorkspaceChannelConnection.connection_id == ChannelConnection.id,
            )
            .where(
                ChannelConnection.tenant_id == principal.tenant_id,
                ChannelConnection.provider == ChannelProvider.TELEGRAM.value,
                ChannelConnection.status != "disabled",
                WorkspaceChannelConnection.tenant_id == principal.tenant_id,
                WorkspaceChannelConnection.workspace_id == principal.workspace_id,
            )
            .with_for_update()
        )
    ).all()
    matches = [
        connection
        for connection, scope in rows
        if (scope.agent_id is None or scope.agent_id == conversation.agent_id)
        and str((connection.configuration_json or {}).get("agentId") or "") == str(conversation.agent_id)
    ]
    if not matches:
        raise HTTPException(status_code=409, detail="Telegram is not connected for this agent")
    if len(matches) > 1:
        raise HTTPException(
            status_code=409,
            detail="Multiple Telegram connections match this agent; disable the duplicate connection before replying",
        )
    connection = matches[0]
    try:
        credentials = (
            credential_store.decrypt(connection.credentials_encrypted)
            if connection.credentials_encrypted
            else {}
        )
    except CredentialStoreError as exc:
        raise HTTPException(status_code=409, detail="Telegram credentials require reconnection") from exc
    if not credentials.get("bot_token"):
        raise HTTPException(status_code=409, detail="Telegram bot token is not configured")
    if not credentials.get("webhook_secret"):
        raise HTTPException(status_code=409, detail="Telegram webhook secret is not configured")
    return connection, chat_id


async def _instagram_connection_for_conversation(
    session: AsyncSession,
    principal: Principal,
    conversation: Conversation,
) -> tuple[ChannelConnection, str] | None:
    recipient_id = _instagram_recipient_id(conversation)
    if recipient_id is None:
        return None
    rows = (
        await session.execute(
            select(ChannelConnection, WorkspaceChannelConnection)
            .join(
                WorkspaceChannelConnection,
                WorkspaceChannelConnection.connection_id == ChannelConnection.id,
            )
            .where(
                ChannelConnection.tenant_id == principal.tenant_id,
                ChannelConnection.provider == ChannelProvider.INSTAGRAM.value,
                ChannelConnection.status != "disabled",
                WorkspaceChannelConnection.tenant_id == principal.tenant_id,
                WorkspaceChannelConnection.workspace_id == principal.workspace_id,
            )
            .with_for_update()
        )
    ).all()
    matches = [
        connection
        for connection, scope in rows
        if (scope.agent_id is None or scope.agent_id == conversation.agent_id)
        and str((connection.configuration_json or {}).get("agentId") or "") == str(conversation.agent_id)
    ]
    if not matches:
        raise HTTPException(status_code=409, detail="Instagram is not connected for this agent")
    if len(matches) > 1:
        raise HTTPException(
            status_code=409,
            detail="Multiple Instagram connections match this agent; disable the duplicate connection before replying",
        )
    connection = matches[0]
    try:
        credentials = (
            credential_store.decrypt(connection.credentials_encrypted)
            if connection.credentials_encrypted
            else {}
        )
    except CredentialStoreError as exc:
        raise HTTPException(status_code=409, detail="Instagram credentials require reconnection") from exc
    if not credentials.get("access_token"):
        raise HTTPException(status_code=409, detail="Instagram access token is not configured")
    if not credentials.get("app_secret"):
        raise HTTPException(status_code=409, detail="Instagram app secret is not configured")
    if not credentials.get("verify_token"):
        raise HTTPException(status_code=409, detail="Instagram webhook verify token is not configured")
    if not str((connection.configuration_json or {}).get("instagramAccountId") or ""):
        raise HTTPException(status_code=409, detail="Instagram professional account ID is not configured")
    return connection, recipient_id


async def _facebook_messenger_connection_for_conversation(
    session: AsyncSession,
    principal: Principal,
    conversation: Conversation,
) -> tuple[ChannelConnection, str] | None:
    recipient_id = _facebook_messenger_recipient_id(conversation)
    if recipient_id is None:
        return None
    rows = (
        await session.execute(
            select(ChannelConnection, WorkspaceChannelConnection)
            .join(
                WorkspaceChannelConnection,
                WorkspaceChannelConnection.connection_id == ChannelConnection.id,
            )
            .where(
                ChannelConnection.tenant_id == principal.tenant_id,
                ChannelConnection.provider == ChannelProvider.FACEBOOK_MESSENGER.value,
                ChannelConnection.status != "disabled",
                WorkspaceChannelConnection.tenant_id == principal.tenant_id,
                WorkspaceChannelConnection.workspace_id == principal.workspace_id,
            )
            .with_for_update()
        )
    ).all()
    matches = [
        connection
        for connection, scope in rows
        if (scope.agent_id is None or scope.agent_id == conversation.agent_id)
        and str((connection.configuration_json or {}).get("agentId") or "") == str(conversation.agent_id)
    ]
    if not matches:
        raise HTTPException(status_code=409, detail="Facebook Messenger is not connected for this agent")
    if len(matches) > 1:
        raise HTTPException(
            status_code=409,
            detail=(
                "Multiple Facebook Messenger connections match this agent; "
                "disable the duplicate connection before replying"
            ),
        )
    connection = matches[0]
    try:
        credentials = (
            credential_store.decrypt(connection.credentials_encrypted)
            if connection.credentials_encrypted
            else {}
        )
    except CredentialStoreError as exc:
        raise HTTPException(
            status_code=409,
            detail="Facebook Messenger credentials require reconnection",
        ) from exc
    if not credentials.get("page_access_token"):
        raise HTTPException(status_code=409, detail="Facebook Page access token is not configured")
    if not credentials.get("app_secret"):
        raise HTTPException(status_code=409, detail="Facebook app secret is not configured")
    if not credentials.get("verify_token"):
        raise HTTPException(status_code=409, detail="Facebook webhook verify token is not configured")
    if not str((connection.configuration_json or {}).get("pageId") or ""):
        raise HTTPException(status_code=409, detail="Facebook Page ID is not configured")
    return connection, recipient_id


async def _slack_connection_for_conversation(
    session: AsyncSession,
    principal: Principal,
    conversation: Conversation,
) -> tuple[ChannelConnection, str] | None:
    target = _slack_delivery_target(conversation)
    if target is None:
        return None
    rows = (
        await session.execute(
            select(ChannelConnection, WorkspaceChannelConnection)
            .join(
                WorkspaceChannelConnection,
                WorkspaceChannelConnection.connection_id == ChannelConnection.id,
            )
            .where(
                ChannelConnection.tenant_id == principal.tenant_id,
                ChannelConnection.provider == ChannelProvider.SLACK.value,
                ChannelConnection.status != "disabled",
                WorkspaceChannelConnection.tenant_id == principal.tenant_id,
                WorkspaceChannelConnection.workspace_id == principal.workspace_id,
            )
            .with_for_update()
        )
    ).all()
    matches = [
        connection
        for connection, scope in rows
        if (scope.agent_id is None or scope.agent_id == conversation.agent_id)
        and str((connection.configuration_json or {}).get("agentId") or "") == str(conversation.agent_id)
    ]
    if not matches:
        raise HTTPException(status_code=409, detail="Slack is not connected for this agent")
    if len(matches) > 1:
        raise HTTPException(
            status_code=409,
            detail="Multiple Slack connections match this agent; disable the duplicate connection before replying",
        )
    connection = matches[0]
    try:
        credentials = (
            credential_store.decrypt(connection.credentials_encrypted)
            if connection.credentials_encrypted
            else {}
        )
    except CredentialStoreError as exc:
        raise HTTPException(status_code=409, detail="Slack credentials require reconnection") from exc
    if not credentials.get("bot_token"):
        raise HTTPException(status_code=409, detail="Slack bot token is not configured")
    if not credentials.get("signing_secret"):
        raise HTTPException(status_code=409, detail="Slack signing secret is not configured")
    return connection, target


@router.get("", response_model=PageResult[ConversationOut])
async def list_conversations(
    principal: ConversationsViewPrincipal,
    session: DB,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    agent_id: UUID | None = Query(default=None),
    channel: Channel | None = Query(default=None),
    state: str | None = Query(default=None, max_length=40),
    purpose: AgentPurpose | None = Query(default=None),
    search: str | None = Query(default=None, max_length=320),
) -> PageResult[ConversationOut]:
    conditions = [
        Conversation.tenant_id == principal.tenant_id,
        Conversation.workspace_id == principal.workspace_id,
    ]
    if principal.agent_ids is not None:
        conditions.append(Conversation.agent_id.in_(principal.agent_ids))
    if purpose is AgentPurpose.EDUCATION:
        conditions.append(education_source(Conversation))
    elif purpose is not None:
        conditions.append(~education_source(Conversation))
        lead_agents = select(AgentPurposeSetting.agent_id).where(
            AgentPurposeSetting.tenant_id == principal.tenant_id,
            AgentPurposeSetting.workspace_id == principal.workspace_id,
            AgentPurposeSetting.purpose == AgentPurpose.LEAD_GENERATION.value,
        )
        conditions.append(
            Conversation.agent_id.in_(lead_agents)
            if purpose is AgentPurpose.LEAD_GENERATION
            else Conversation.agent_id.not_in(lead_agents)
        )
    if agent_id:
        conditions.append(Conversation.agent_id == agent_id)
    if channel:
        conditions.append(Conversation.channel == channel)
    if state:
        conditions.append(Conversation.state == state)
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        conditions.append(
            or_(
                Conversation.visitor_name.ilike(pattern),
                Conversation.visitor_email.ilike(pattern),
                Conversation.visitor_id.ilike(pattern),
            )
        )
    total = int(await session.scalar(select(func.count()).select_from(Conversation).where(*conditions)) or 0)
    rows = (
        await session.scalars(
            select(Conversation)
            .options(conversation_options())
            .where(*conditions)
            .order_by(conversation_activity_order().desc(), Conversation.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    items = [conversation_response(item) for item in rows]
    await attach_whatsapp_message_status(session, rows, items)
    await attach_lead_status(session, principal, items)
    return PageResult(items=items, total=total, page=page, page_size=page_size)


@router.get("/{conversation_id}", response_model=ConversationOut)
async def get_conversation(
    conversation_id: UUID, principal: ConversationsViewPrincipal, session: DB
) -> ConversationOut:
    conversation = await session.scalar(
        select(Conversation)
        .options(conversation_options())
        .where(*conversation_scope(principal, conversation_id))
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    response = conversation_response(conversation)
    await attach_whatsapp_message_status(session, [conversation], [response])
    await attach_lead_status(session, principal, [response])
    return response


@router.post("/{conversation_id}/resolve", response_model=ConversationOut)
async def resolve_conversation(
    conversation_id: UUID,
    principal: ConversationsResolvePrincipal,
    session: DB,
    payload: ConversationResolve | None = None,
) -> ConversationOut:
    """Resolve a conversation and atomically create/finalize its linked Lead.

    The conversation and every message remain stored. Repeating this request is
    idempotent: it reconciles the existing Lead rather than creating another.
    """
    if payload and payload.lead_status is not None and not principal.can("leads.update"):
        raise HTTPException(status_code=403, detail="You do not have permission to update lead status")
    conversation = await locked_conversation(session, principal, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if await conversation_purpose(session, conversation) is AgentPurpose.EDUCATION:
        raise HTTPException(status_code=409, detail=EDUCATION_WORKFLOW_MESSAGE)
    resolution = await conversation_resolution_service.resolve(
        session,
        conversation=conversation,
        actor_user_id=principal.user_id,
        create_lead=True,
    )
    if payload and payload.lead_status is not None and resolution.lead is not None:
        await lead_domain_service.update_status(
            session,
            lead=resolution.lead,
            status=payload.lead_status,
            actor_id=str(principal.user_id),
            correlation_id=request_id_ctx.get(),
            qualification_reason="Marked Qualified in Conversations",
            skip_unchanged=True,
        )
    await session.commit()
    await session.refresh(conversation)
    response = conversation_response(conversation)
    await attach_lead_status(session, principal, [response])
    return response


@router.patch("/{conversation_id}", response_model=ConversationOut)
async def update_conversation(
    conversation_id: UUID,
    payload: ConversationPatch,
    principal: ConversationsResolvePrincipal,
    session: DB,
) -> ConversationOut:
    conversation = await locked_conversation(session, principal, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if (
        payload.state == ConversationState.RESOLVED
        and await conversation_purpose(session, conversation) is AgentPurpose.EDUCATION
    ):
        raise HTTPException(status_code=409, detail=EDUCATION_WORKFLOW_MESSAGE)
    previous_state = conversation.state
    patch = payload.model_dump(exclude_unset=True)
    requested_state = payload.state
    patch.pop("state", None)
    if "visitor_name" in patch and not (patch["visitor_name"] or "").strip():
        raise HTTPException(status_code=422, detail="Visitor name cannot be empty")
    details = patch.pop("visitor_details", None)
    if details is not None:
        conversation.visitor_details = {**(conversation.visitor_details or {}), **details}
    for name, value in patch.items():
        setattr(conversation, "unread_count" if name == "unread" else name, value)

    if requested_state == ConversationState.RESOLVED:
        await conversation_resolution_service.resolve(
            session,
            conversation=conversation,
            actor_user_id=principal.user_id,
        )
    elif requested_state is not None and requested_state != previous_state:
        conversation.state = requested_state
        conversation.ended_at = None
        event_payload = {
            "conversationId": str(conversation.id),
            "workspaceId": str(conversation.workspace_id),
            "agentId": str(conversation.agent_id),
            "previousState": previous_state.value,
            "state": requested_state.value,
        }
        enqueue_event(
            session,
            tenant_id=principal.tenant_id,
            aggregate_type="conversation",
            aggregate_id=conversation.id,
            event_type="conversation.state.changed.v1",
            payload=event_payload,
        )
        if previous_state == ConversationState.RESOLVED and requested_state == ConversationState.OPEN:
            enqueue_event(
                session,
                tenant_id=principal.tenant_id,
                aggregate_type="conversation",
                aggregate_id=conversation.id,
                event_type="conversation.reopened.v1",
                payload=event_payload,
            )

    if payload.model_fields_set & {"visitor_name", "visitor_email", "page_url", "visitor_details"}:
        from northstar_api.services.visitor_details import update_linked_lead

        await update_linked_lead(session, conversation, payload.model_fields_set)

    await session.commit()
    await session.refresh(conversation)
    response = conversation_response(conversation)
    await attach_lead_status(session, principal, [response])
    return response


@router.post("/{conversation_id}/messages", response_model=MessageOut, status_code=201)
async def reply_to_conversation(
    conversation_id: UUID,
    payload: ConversationReplyCreate,
    principal: ConversationsReplyPrincipal,
    session: DB,
) -> MessageOut:
    conversation = await session.scalar(
        select(Conversation).where(*conversation_scope(principal, conversation_id)).with_for_update()
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    whatsapp_connection: WhatsAppConnection | None = None
    template_payload = None
    message_content = payload.content.strip()
    message_format = payload.message_format.model_dump() if payload.message_format else {"type": "text"}
    format_type = message_format.get("type", "text")
    if payload.whatsapp_template and payload.message_format and format_type != "text":
        raise HTTPException(status_code=422, detail="A WhatsApp template cannot use another message format")
    if format_type == "buttons":
        buttons = message_format.get("buttons") or []
        if not buttons:
            raise HTTPException(status_code=422, detail="Add at least one quick-reply button")
        if len(message_content) > 1024:
            raise HTTPException(status_code=422, detail="Button message body cannot exceed 1024 characters")
        message_format.pop("table", None)
    elif format_type == "table":
        table = message_format.get("table")
        if not table:
            raise HTTPException(status_code=422, detail="Add table columns and rows")
        columns = table["columns"]
        rows = table["rows"]
        if any(len(row) != len(columns) for row in rows):
            raise HTTPException(status_code=422, detail="Every table row must match the number of columns")
        message_format["body"] = message_content
        rendered_rows = [" | ".join(columns), " | ".join("---" for _ in columns)]
        rendered_rows.extend(" | ".join(row) for row in rows)
        message_content = f"{message_content}\n\n" + "\n".join(rendered_rows)
        message_format.pop("buttons", None)
    elif format_type in {
        "list",
        "image",
        "video",
        "audio",
        "document",
        "sticker",
        "location",
        "contact",
        "cta_url",
        "flow",
        "product",
        "product_list",
        "catalog",
    }:
        config = message_format.get("config") or {}
        if format_type in {"image", "video", "audio", "document", "sticker"} and not (
            config.get("url") or config.get("mediaId")
        ):
            raise HTTPException(status_code=422, detail="Add a public media URL or uploaded media ID")
        if format_type == "location" and not (config.get("latitude") and config.get("longitude")):
            raise HTTPException(status_code=422, detail="Location requires latitude and longitude")
        if format_type == "contact" and not config.get("contact"):
            raise HTTPException(status_code=422, detail="Add contact details")
        if format_type in {
            "list",
            "cta_url",
            "flow",
            "product",
            "product_list",
            "catalog",
        } and not config.get("action"):
            raise HTTPException(status_code=422, detail="Add the WhatsApp action configuration")
        message_format.pop("buttons", None)
        message_format.pop("table", None)
    else:
        message_format = {"type": "text"}
    if payload.whatsapp_template and conversation.channel != Channel.WHATSAPP:
        raise HTTPException(status_code=422, detail="Templates are only available for WhatsApp conversations")
    telegram_target: tuple[ChannelConnection, str] | None = None
    instagram_target: tuple[ChannelConnection, str] | None = None
    messenger_target: tuple[ChannelConnection, str] | None = None
    slack_target: tuple[ChannelConnection, str] | None = None
    if conversation.channel == Channel.WHATSAPP:
        if not conversation.visitor_id or not conversation.visitor_id.isdigit():
            raise HTTPException(status_code=409, detail="WhatsApp recipient is unavailable")
        whatsapp_connection = await session.scalar(
            select(WhatsAppConnection)
            .where(
                WhatsAppConnection.tenant_id == principal.tenant_id,
                WhatsAppConnection.workspace_id == principal.workspace_id,
                WhatsAppConnection.agent_id == conversation.agent_id,
                WhatsAppConnection.status == "connected",
            )
            .with_for_update()
        )
        if not whatsapp_connection:
            raise HTTPException(status_code=409, detail="WhatsApp is not connected for this agent")
        if not token_expiry_is_current(whatsapp_connection.token_expires_at):
            raise HTTPException(
                status_code=409,
                detail="WhatsApp authorization expired; reconnect the integration",
            )
        latest_customer_message = await session.scalar(
            select(
                func.max(
                    func.coalesce(
                        WhatsAppInboundMessage.provider_timestamp,
                        WhatsAppInboundMessage.created_at,
                    )
                )
            ).where(
                WhatsAppInboundMessage.tenant_id == principal.tenant_id,
                WhatsAppInboundMessage.workspace_id == principal.workspace_id,
                WhatsAppInboundMessage.connection_id == whatsapp_connection.id,
                or_(
                    WhatsAppInboundMessage.conversation_id == conversation.id,
                    WhatsAppInboundMessage.sender_wa_id == conversation.visitor_id,
                ),
                WhatsAppInboundMessage.status.not_in(("ignored", "cancelled")),
                WhatsAppInboundMessage.message_text != "",
            )
        )
        if latest_customer_message is not None and latest_customer_message.tzinfo is None:
            latest_customer_message = latest_customer_message.replace(tzinfo=UTC)
        now = datetime.now(UTC)
        if not payload.whatsapp_template and (
            latest_customer_message is None
            or latest_customer_message < now - timedelta(hours=24)
            or latest_customer_message > now + timedelta(minutes=5)
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "The 24-hour WhatsApp customer-service window is closed; "
                    "send an approved template instead"
                ),
            )
        if payload.whatsapp_template:
            selection = payload.whatsapp_template
            try:
                provider_client, access_token = await connection_client(session, whatsapp_connection)
                templates = await provider_client.list_templates(
                    access_token,
                    waba_id=whatsapp_connection.waba_id,
                )
                template = next(
                    (
                        item
                        for item in templates
                        if item.get("name") == selection.name and item.get("language") == selection.language
                    ),
                    None,
                )
                if template is None:
                    raise ValueError("The selected template is no longer approved or available")
                template_payload, message_content = build_template(template, selection.parameters)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from None
            except (WhatsAppGraphError, WhatsAppConfigurationError) as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from None
    else:
        telegram_target = await _telegram_connection_for_conversation(
            session,
            principal,
            conversation,
        )
        if telegram_target is None:
            instagram_target = await _instagram_connection_for_conversation(
                session,
                principal,
                conversation,
            )
        if telegram_target is None and instagram_target is None:
            messenger_target = await _facebook_messenger_connection_for_conversation(
                session,
                principal,
                conversation,
            )
        if telegram_target is None and instagram_target is None and messenger_target is None:
            slack_target = await _slack_connection_for_conversation(
                session,
                principal,
                conversation,
            )
    sequence = int(
        await session.scalar(
            select(func.coalesce(func.max(Message.sequence), 0)).where(
                Message.conversation_id == conversation.id,
                Message.tenant_id == principal.tenant_id,
            )
        )
        or 0
    )
    queued_external = (
        whatsapp_connection is not None
        or telegram_target is not None
        or instagram_target is not None
        or messenger_target is not None
        or slack_target is not None
    )
    message = Message(
        tenant_id=principal.tenant_id,
        workspace_id=conversation.workspace_id,
        conversation_id=conversation.id,
        sequence=sequence + 1,
        role=MessageRole.AGENT,
        content=message_content,
        content_json=message_format,
        finish_reason="queued" if queued_external else "sent",
    )
    session.add(message)
    conversation.updated_at = datetime.now(UTC)
    await session.flush()
    delivery: WhatsAppOutboundDelivery | None = None
    telegram_delivery: ChannelOutboundDelivery | None = None
    instagram_delivery: ChannelOutboundDelivery | None = None
    messenger_delivery: ChannelOutboundDelivery | None = None
    slack_delivery: ChannelOutboundDelivery | None = None
    if whatsapp_connection:
        delivery = WhatsAppOutboundDelivery(
            tenant_id=principal.tenant_id,
            workspace_id=conversation.workspace_id,
            connection_id=whatsapp_connection.id,
            phone_number_id=whatsapp_connection.phone_number_id,
            message_id=message.id,
            recipient_wa_id=conversation.visitor_id or "",
            template_payload=template_payload,
            status="queued",
        )
        session.add(delivery)
        await session.flush()
    elif telegram_target:
        telegram_connection, chat_id = telegram_target
        telegram_delivery = ChannelOutboundDelivery(
            tenant_id=principal.tenant_id,
            workspace_id=conversation.workspace_id,
            connection_id=telegram_connection.id,
            message_id=message.id,
            provider=ChannelProvider.TELEGRAM.value,
            recipient_external_id=chat_id,
            status="queued",
        )
        session.add(telegram_delivery)
        await session.flush()
    elif instagram_target:
        instagram_connection, recipient_id = instagram_target
        instagram_delivery = ChannelOutboundDelivery(
            tenant_id=principal.tenant_id,
            workspace_id=conversation.workspace_id,
            connection_id=instagram_connection.id,
            message_id=message.id,
            provider=ChannelProvider.INSTAGRAM.value,
            recipient_external_id=recipient_id,
            status="queued",
        )
        session.add(instagram_delivery)
        await session.flush()
    elif messenger_target:
        messenger_connection, recipient_id = messenger_target
        messenger_delivery = ChannelOutboundDelivery(
            tenant_id=principal.tenant_id,
            workspace_id=conversation.workspace_id,
            connection_id=messenger_connection.id,
            message_id=message.id,
            provider=ChannelProvider.FACEBOOK_MESSENGER.value,
            recipient_external_id=recipient_id,
            status="queued",
        )
        session.add(messenger_delivery)
        await session.flush()
    elif slack_target:
        slack_connection, target = slack_target
        slack_delivery = ChannelOutboundDelivery(
            tenant_id=principal.tenant_id,
            workspace_id=conversation.workspace_id,
            connection_id=slack_connection.id,
            message_id=message.id,
            provider=ChannelProvider.SLACK.value,
            recipient_external_id=target,
            status="queued",
        )
        session.add(slack_delivery)
        await session.flush()
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="conversation",
        aggregate_id=conversation.id,
        event_type="chat.message.created.v1",
        payload={
            "conversationId": str(conversation.id),
            "workspaceId": str(conversation.workspace_id),
            "agentId": str(conversation.agent_id),
            "messageId": str(message.id),
            "role": "agent",
        },
    )
    await session.commit()
    if delivery:
        try:
            await asyncio.to_thread(
                send_whatsapp_human_reply.apply_async,
                args=[str(delivery.id)],
                queue="whatsapp.outbound",
                routing_key="whatsapp.outbound",
            )
            delivery.dispatch_attempts += 1
            delivery.dispatched_at = datetime.now(UTC)
            delivery.next_dispatch_at = datetime.now(UTC) + timedelta(minutes=5)
            delivery.last_error = None
        except Exception:
            # The durable dispatcher will retry this database-backed delivery.
            delivery.dispatch_attempts += 1
            exhausted = delivery.dispatch_attempts >= get_settings().whatsapp_dispatch_max_attempts
            delivery.status = "dispatch_failed" if exhausted else "failed"
            delivery.next_dispatch_at = None if exhausted else datetime.now(UTC)
            delivery.last_error = "queue dispatch unavailable"
        await session.commit()
    elif telegram_delivery:
        try:
            await asyncio.to_thread(
                send_telegram_message.apply_async,
                args=[str(telegram_delivery.id)],
                queue="telegram.outbound",
                routing_key="telegram.outbound",
            )
            telegram_delivery.dispatch_attempts += 1
            telegram_delivery.dispatched_at = datetime.now(UTC)
            telegram_delivery.next_dispatch_at = datetime.now(UTC) + timedelta(minutes=5)
            telegram_delivery.last_error = None
        except Exception:
            # The durable dispatcher will retry this database-backed delivery.
            telegram_delivery.dispatch_attempts += 1
            telegram_delivery.status = "failed"
            telegram_delivery.next_dispatch_at = datetime.now(UTC)
            telegram_delivery.last_error = "queue dispatch unavailable"
        await session.commit()
    elif instagram_delivery:
        try:
            await asyncio.to_thread(
                send_instagram_message.apply_async,
                args=[str(instagram_delivery.id)],
                queue="instagram.outbound",
                routing_key="instagram.outbound",
            )
            instagram_delivery.dispatch_attempts += 1
            instagram_delivery.dispatched_at = datetime.now(UTC)
            instagram_delivery.next_dispatch_at = datetime.now(UTC) + timedelta(minutes=5)
            instagram_delivery.last_error = None
        except Exception:
            # The durable dispatcher will retry this database-backed delivery.
            instagram_delivery.dispatch_attempts += 1
            instagram_delivery.status = "failed"
            instagram_delivery.next_dispatch_at = datetime.now(UTC)
            instagram_delivery.last_error = "queue dispatch unavailable"
        await session.commit()
    elif messenger_delivery:
        try:
            await asyncio.to_thread(
                send_facebook_messenger_message.apply_async,
                args=[str(messenger_delivery.id)],
                queue="facebook_messenger.outbound",
                routing_key="facebook_messenger.outbound",
            )
            messenger_delivery.dispatch_attempts += 1
            messenger_delivery.dispatched_at = datetime.now(UTC)
            messenger_delivery.next_dispatch_at = datetime.now(UTC) + timedelta(minutes=5)
            messenger_delivery.last_error = None
        except Exception:
            # The durable dispatcher will retry this database-backed delivery.
            messenger_delivery.dispatch_attempts += 1
            messenger_delivery.status = "failed"
            messenger_delivery.next_dispatch_at = datetime.now(UTC)
            messenger_delivery.last_error = "queue dispatch unavailable"
        await session.commit()
    elif slack_delivery:
        try:
            await asyncio.to_thread(
                send_slack_message.apply_async,
                args=[str(slack_delivery.id)],
                queue="slack.outbound",
                routing_key="slack.outbound",
            )
            slack_delivery.dispatch_attempts += 1
            slack_delivery.dispatched_at = datetime.now(UTC)
            slack_delivery.next_dispatch_at = datetime.now(UTC) + timedelta(minutes=5)
            slack_delivery.last_error = None
        except Exception:
            # The durable dispatcher will retry this database-backed delivery.
            slack_delivery.dispatch_attempts += 1
            slack_delivery.status = "failed"
            slack_delivery.next_dispatch_at = datetime.now(UTC)
            slack_delivery.last_error = "queue dispatch unavailable"
        await session.commit()
    await session.refresh(message)
    return MessageOut(
        id=message.id,
        role=message.role,
        content=message.content,
        created_at=message.created_at,
        citations=[],
        message_format=message.content_json or None,
    )
