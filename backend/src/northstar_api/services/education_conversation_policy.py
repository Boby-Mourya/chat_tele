from uuid import UUID

from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from northstar_api.agent_purpose import AgentPurpose, AgentPurposeSetting, get_agent_purpose
from northstar_api.education_conversation_context import EducationConversationContext
from northstar_api.models import Conversation, Lead

EDUCATION_WORKFLOW_MESSAGE = (
    "Education chats stay in Conversations and cannot be resolved or converted to leads."
)


def education_source(model: type[Lead] | type[Conversation]) -> ColumnElement[bool]:
    """Education remains separate even if a historical chat's agent is repurposed."""
    conversation_id = model.conversation_id if model is Lead else model.id
    return or_(
        exists(
            select(AgentPurposeSetting.agent_id)
            .where(
                AgentPurposeSetting.tenant_id == model.tenant_id,
                AgentPurposeSetting.workspace_id == model.workspace_id,
                AgentPurposeSetting.agent_id == model.agent_id,
                AgentPurposeSetting.purpose == AgentPurpose.EDUCATION.value,
            )
            .correlate(model)
        ),
        exists(
            select(EducationConversationContext.id)
            .where(
                EducationConversationContext.tenant_id == model.tenant_id,
                EducationConversationContext.workspace_id == model.workspace_id,
                EducationConversationContext.conversation_id == conversation_id,
            )
            .correlate(model)
        ),
    )


async def is_education_lead(session: AsyncSession, lead_id: UUID) -> bool:
    return await session.scalar(select(Lead.id).where(Lead.id == lead_id, education_source(Lead))) is not None


async def conversation_purpose(session: AsyncSession, conversation: Conversation) -> AgentPurpose:
    if (
        await session.scalar(
            select(Conversation.id).where(
                Conversation.id == conversation.id,
                education_source(Conversation),
            )
        )
        is not None
    ):
        return AgentPurpose.EDUCATION
    return await get_agent_purpose(
        session,
        tenant_id=conversation.tenant_id,
        workspace_id=conversation.workspace_id,
        agent_id=conversation.agent_id,
    )
