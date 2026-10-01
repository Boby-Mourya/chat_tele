"""Compatibility entry points for the course-release-aware Education runtime."""
from __future__ import annotations

from contextvars import ContextVar
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.agent_purpose import AgentPurpose, get_agent_purpose
from northstar_api.models import Agent
from northstar_api.modules.knowledge.retrieval import (
    EducationRetrievalScope,
    Evidence,
    RetrievalService,
)
from northstar_api.services.course_knowledge import Boundary, resolve_context, retrieve_course_evidence
from northstar_api.services.course_knowledge_chat import CourseKnowledgeChatCoordinator
from northstar_api.services.education_rag import EducationRagAccessDenied

_education_scope: ContextVar[EducationRetrievalScope | None] = ContextVar("education_retrieval_scope", default=None)


class EducationScopedRetrieval(RetrievalService):
    """Legacy imports retain the same fail-closed, active-release boundary."""
    def __init__(self, base: RetrievalService) -> None:
        self.base, self.model, self.settings = base, base.model, base.settings

    async def retrieve(self, session: AsyncSession, *, tenant_id: UUID, agent_id: UUID, revision: int,
        query: str, education_scope: EducationRetrievalScope | None = None,
        rerank_candidates: int | None = None, final_context_chunks: int | None = None) -> list[Evidence]:
        agent = await session.scalar(select(Agent).where(Agent.id == agent_id, Agent.tenant_id == tenant_id))
        if agent is None:
            return []
        purpose = await get_agent_purpose(session, tenant_id=tenant_id, workspace_id=agent.workspace_id, agent_id=agent_id)
        if purpose is not AgentPurpose.EDUCATION:
            return await self.base.retrieve(session, tenant_id=tenant_id, agent_id=agent_id, revision=revision,
                query=query, education_scope=education_scope, rerank_candidates=rerank_candidates, final_context_chunks=final_context_chunks)
        scope = education_scope or _education_scope.get()
        if scope is None or scope.workspace_id != agent.workspace_id:
            raise EducationRagAccessDenied("education_context_missing")
        boundary = Boundary(tenant_id, agent.workspace_id, agent.id)
        context = await resolve_context(session, boundary, scope.enrollment_id, expected_student_id=scope.student_id,
            expected_course_id=scope.course_id, expected_batch_id=scope.batch_id)
        return await retrieve_course_evidence(session, boundary, context, query, model=self.model,
            candidate_limit=rerank_candidates or 60, result_limit=final_context_chunks or 8)


EducationAwareChatCoordinator = CourseKnowledgeChatCoordinator
education_chat_coordinator = CourseKnowledgeChatCoordinator()
