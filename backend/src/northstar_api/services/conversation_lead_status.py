from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.agent_purpose import AgentPurpose, AgentPurposeSetting
from northstar_api.models import Conversation, Lead
from northstar_api.schemas import ConversationOut
from northstar_api.security import Principal
from northstar_api.services.education_conversation_policy import education_source


async def attach_lead_status(
    session: AsyncSession, principal: Principal, conversations: Sequence[ConversationOut]
) -> None:
    """Load purpose and lead status in scoped batch queries for either inbox."""
    if not conversations:
        return
    by_id = {item.id: item for item in conversations}
    purposes = dict(
        (
            await session.execute(
                select(AgentPurposeSetting.agent_id, AgentPurposeSetting.purpose).where(
                    AgentPurposeSetting.tenant_id == principal.tenant_id,
                    AgentPurposeSetting.workspace_id == principal.workspace_id,
                    AgentPurposeSetting.agent_id.in_({item.agent_id for item in conversations}),
                )
            )
        ).all()
    )
    education_ids = set(
        await session.scalars(
            select(Conversation.id).where(
                Conversation.id.in_(by_id),
                Conversation.tenant_id == principal.tenant_id,
                Conversation.workspace_id == principal.workspace_id,
                education_source(Conversation),
            )
        )
    )
    leads = await session.execute(
        select(Lead.id, Lead.conversation_id, Lead.agent_id, Lead.status).where(
            Lead.tenant_id == principal.tenant_id,
            Lead.workspace_id == principal.workspace_id,
            Lead.conversation_id.in_(by_id),
            ~education_source(Lead),
        )
    )
    for item in conversations:
        item.purpose = (
            AgentPurpose.EDUCATION
            if item.id in education_ids
            else AgentPurpose(purposes.get(item.agent_id, "support"))
        )
        item.can_update_lead_status = item.purpose != AgentPurpose.EDUCATION and principal.can("leads.update")
    for lead_id, conversation_id, agent_id, status in leads:
        item = by_id[conversation_id]
        if item.agent_id == agent_id:
            item.lead_id = lead_id
            item.lead_status = status
