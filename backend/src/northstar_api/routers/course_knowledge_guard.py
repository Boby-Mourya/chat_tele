"""Normal Education uploads must declare their destination before ingestion.

Registered before the legacy Knowledge router. Support/lead-generation behavior
is delegated unchanged; pre-existing unassigned Education files remain inspectable.
"""
from uuid import UUID

from fastapi import APIRouter, HTTPException

from northstar_api.agent_purpose import AgentPurpose, get_agent_purpose
from northstar_api.routers.agents import scoped_agent
from northstar_api.routers.knowledge import DB, KnowledgeManagePrincipal, add_knowledge
from northstar_api.schemas import KnowledgeCreate, KnowledgeOut

router = APIRouter(tags=["course-knowledge"])


@router.post("/agents/{agent_id}/knowledge", response_model=KnowledgeOut, status_code=201)
async def education_upload_guard(agent_id: UUID, payload: KnowledgeCreate, principal: KnowledgeManagePrincipal, session: DB) -> KnowledgeOut:
    if principal.agent_ids is not None and agent_id not in principal.agent_ids:
        raise HTTPException(404, "Agent not found")
    agent = await scoped_agent(session, principal.tenant_id, agent_id, workspace_id=principal.workspace_id)
    if (
        await get_agent_purpose(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=agent.workspace_id,
            agent_id=agent.id,
        )
        is AgentPurpose.EDUCATION
        and payload.education_destination is None
    ):
        raise HTTPException(409, "Select course and curriculum first: use /agents/{agent_id}/education-knowledge/uploads")
    return await add_knowledge(agent_id, payload, principal, session)
