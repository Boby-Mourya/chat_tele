from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Load, selectinload

from northstar_api.agent_purpose import AgentPurpose
from northstar_api.services.conversation_activity import conversation_activity_order, conversation_activity_time
from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.education_conversation_context import EducationConversationContext
from northstar_api.models import Channel, Conversation, ConversationState, Message
from northstar_api.modules.whatsapp.status import attach_whatsapp_message_status
from northstar_api.schemas import CitationOut, ConversationOut, MessageOut, PageResult
from northstar_api.security import Principal
from northstar_api.services.conversation_lead_status import attach_lead_status

router = APIRouter(prefix="/education/conversations", tags=["education"])
DB = Annotated[AsyncSession, Depends(get_session)]
ConversationsViewPrincipal = Annotated[
    Principal,
    Depends(require_permissions("conversations.view")),
]


def _conversation_options() -> Load:
    return cast(Load, selectinload(Conversation.messages).selectinload(Message.citations))


def _conversation_response(conversation: Conversation) -> ConversationOut:
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
        channel=conversation.channel,
        state=conversation.state,
        sentiment=conversation.sentiment,
        preview=preview,
        unread=conversation.unread_count,
        started_at=conversation.started_at,
        updated_at=conversation_activity_time(conversation),
        messages=messages,
    )


@router.get("", response_model=PageResult[ConversationOut])
async def list_education_conversations(
    principal: ConversationsViewPrincipal,
    session: DB,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    agent_id: UUID | None = Query(default=None),
    purpose: AgentPurpose | None = Query(default=None),
    course_id: UUID | None = Query(default=None),
    batch_id: UUID | None = Query(default=None),
    student_id: UUID | None = Query(default=None),
    channel: Channel | None = Query(default=None),
    state: ConversationState | None = Query(default=None),
    search: str | None = Query(default=None, max_length=320),
) -> PageResult[ConversationOut]:
    """List Education conversations through their immutable authorization context.

    This endpoint is intentionally read-only. It composes Education scope with the
    existing workspace, Agent, channel, state and search boundaries without changing
    the generic conversation inbox behavior when Education filters are not used.
    """

    if purpose is not None and purpose is not AgentPurpose.EDUCATION:
        return PageResult(items=[], total=0, page=page, page_size=page_size)

    conditions = [
        Conversation.tenant_id == principal.tenant_id,
        Conversation.workspace_id == principal.workspace_id,
        EducationConversationContext.tenant_id == principal.tenant_id,
        EducationConversationContext.workspace_id == principal.workspace_id,
    ]
    if principal.agent_ids is not None:
        conditions.append(Conversation.agent_id.in_(principal.agent_ids))
    if agent_id is not None:
        conditions.extend(
            (
                Conversation.agent_id == agent_id,
                EducationConversationContext.agent_id == agent_id,
            )
        )
    if course_id is not None:
        conditions.append(EducationConversationContext.course_id == course_id)
    if batch_id is not None:
        conditions.append(EducationConversationContext.batch_id == batch_id)
    if student_id is not None:
        conditions.append(EducationConversationContext.student_id == student_id)
    if channel is not None:
        conditions.append(Conversation.channel == channel)
    if state is not None:
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

    scoped = (
        select(Conversation)
        .join(
            EducationConversationContext,
            EducationConversationContext.conversation_id == Conversation.id,
        )
        .where(*conditions)
    )
    total = int(
        await session.scalar(
            select(func.count(Conversation.id))
            .join(
                EducationConversationContext,
                EducationConversationContext.conversation_id == Conversation.id,
            )
            .where(*conditions)
        )
        or 0
    )
    rows = (
        await session.scalars(
            scoped
            .options(_conversation_options())
            .order_by(conversation_activity_order().desc(), Conversation.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    items = [_conversation_response(item) for item in rows]
    await attach_whatsapp_message_status(session, rows, items)
    await attach_lead_status(session, principal, items)
    return PageResult(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )
