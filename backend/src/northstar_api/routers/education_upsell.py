from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.agent_purpose import AgentPurpose, get_agent_purpose
from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.models import Conversation, ConversationState
from northstar_api.schemas import APIModel
from northstar_api.security import Principal
from northstar_api.services.conversation_resolution import (
    EducationUpsellLeadError,
    conversation_resolution_service,
)

router = APIRouter(prefix="/education/conversations", tags=["education"])
DB = Annotated[AsyncSession, Depends(get_session)]
ConversationsResolvePrincipal = Annotated[
    Principal,
    Depends(require_permissions("conversations.resolve")),
]


class EducationUpsellResolutionOut(APIModel):
    conversation_id: UUID
    state: ConversationState
    lead_id: UUID
    lead_created: bool


@router.post(
    "/{conversation_id}/resolve-sales-intent",
    response_model=EducationUpsellResolutionOut,
)
async def resolve_education_sales_intent(
    conversation_id: UUID,
    principal: ConversationsResolvePrincipal,
    session: DB,
) -> EducationUpsellResolutionOut:
    conditions = [
        Conversation.id == conversation_id,
        Conversation.tenant_id == principal.tenant_id,
        Conversation.workspace_id == principal.workspace_id,
    ]
    if principal.agent_ids is not None:
        conditions.append(Conversation.agent_id.in_(principal.agent_ids))
    conversation = await session.scalar(
        select(Conversation).where(*conditions).with_for_update()
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    purpose = await get_agent_purpose(
        session,
        tenant_id=conversation.tenant_id,
        workspace_id=conversation.workspace_id,
        agent_id=conversation.agent_id,
    )
    if purpose is not AgentPurpose.EDUCATION:
        raise HTTPException(
            status_code=409,
            detail="Sales-intent resolution is only available for Education agents",
        )

    try:
        result = await conversation_resolution_service.resolve(
            session,
            conversation=conversation,
            actor_user_id=principal.user_id,
            sales_intent=True,
        )
    except EducationUpsellLeadError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if result.lead is None:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Education sales-intent resolution did not produce a Lead",
        )

    await session.commit()
    return EducationUpsellResolutionOut(
        conversation_id=conversation.id,
        state=conversation.state,
        lead_id=result.lead.id,
        lead_created=result.lead_created,
    )
