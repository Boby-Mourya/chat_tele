from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.agent_purpose import AgentPurpose, get_agent_purpose
from northstar_api.education import EducationCourse
from northstar_api.education_batches import EducationBatch
from northstar_api.education_curricula import EducationCurriculum
from northstar_api.education_knowledge_lifecycle import EducationSourceVersion
from northstar_api.education_knowledge_schemas import (
    EducationKnowledgeScopeOut,
    EducationKnowledgeScopeRef,
)
from northstar_api.education_knowledge_scope import EducationKnowledgeScope
from northstar_api.education_papers import EducationPaper
from northstar_api.models import Agent


async def require_education_agent(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    agent: Agent,
) -> None:
    purpose = await get_agent_purpose(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        agent_id=agent.id,
    )
    if purpose is not AgentPurpose.EDUCATION:
        raise HTTPException(status_code=409, detail="Education knowledge scope requires an Education Agent")


async def validate_scope_pairs(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    pairs: Sequence[EducationKnowledgeScopeRef],
) -> list[EducationKnowledgeScopeRef]:
    normalized: list[EducationKnowledgeScopeRef] = []
    for pair in pairs:
        course = await session.scalar(
            select(EducationCourse).where(
                EducationCourse.id == pair.course_id,
                EducationCourse.tenant_id == tenant_id,
                EducationCourse.workspace_id == workspace_id,
            )
        )
        if course is None:
            raise HTTPException(status_code=422, detail="Education knowledge scope has an invalid Course")
        batch: EducationBatch | None = None
        if pair.batch_id is not None:
            batch = await session.scalar(
                select(EducationBatch).where(
                    EducationBatch.id == pair.batch_id,
                    EducationBatch.tenant_id == tenant_id,
                    EducationBatch.workspace_id == workspace_id,
                    EducationBatch.course_id == pair.course_id,
                )
            )
            if batch is None:
                raise HTTPException(
                    status_code=422,
                    detail="Education knowledge scope Batch must belong to the selected Course",
                )

        curriculum_id = pair.curriculum_id or (batch.curriculum_id if batch else None)
        if curriculum_id is None:
            raise HTTPException(
                status_code=422,
                detail="Education knowledge scope requires a Curriculum when no Batch is selected",
            )
        curriculum = await session.scalar(
            select(EducationCurriculum).where(
                EducationCurriculum.id == curriculum_id,
                EducationCurriculum.tenant_id == tenant_id,
                EducationCurriculum.workspace_id == workspace_id,
                EducationCurriculum.course_id == pair.course_id,
            )
        )
        if curriculum is None:
            raise HTTPException(
                status_code=422,
                detail="Education knowledge scope Curriculum must belong to the selected Course",
            )
        if batch is not None and batch.curriculum_id not in {None, curriculum.id}:
            raise HTTPException(
                status_code=422,
                detail="Education knowledge scope Batch must use the selected Curriculum",
            )
        if pair.paper_id is not None:
            paper = await session.scalar(
                select(EducationPaper).where(
                    EducationPaper.id == pair.paper_id,
                    EducationPaper.tenant_id == tenant_id,
                    EducationPaper.workspace_id == workspace_id,
                    EducationPaper.course_id == pair.course_id,
                    EducationPaper.curriculum_id == curriculum.id,
                )
            )
            if paper is None:
                raise HTTPException(
                    status_code=422,
                    detail="Education knowledge scope Paper must belong to the selected Curriculum",
                )
        normalized.append(
            EducationKnowledgeScopeRef(
                course_id=pair.course_id,
                curriculum_id=curriculum.id,
                paper_id=pair.paper_id,
                batch_id=pair.batch_id,
                selected_block_ids=pair.selected_block_ids,
                topic_ids=pair.topic_ids,
                material_type=pair.material_type,
            )
        )
    return normalized


def _scope_out(scope: EducationKnowledgeScope) -> EducationKnowledgeScopeOut:
    return EducationKnowledgeScopeOut.model_validate(scope)


async def list_source_scopes(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    agent_id: UUID,
    source_id: UUID,
) -> list[EducationKnowledgeScopeOut]:
    rows = (
        await session.scalars(
            select(EducationKnowledgeScope)
            .where(
                EducationKnowledgeScope.tenant_id == tenant_id,
                EducationKnowledgeScope.workspace_id == workspace_id,
                EducationKnowledgeScope.agent_id == agent_id,
                EducationKnowledgeScope.source_id == source_id,
            )
            .order_by(
                EducationKnowledgeScope.course_id,
                EducationKnowledgeScope.curriculum_id,
                EducationKnowledgeScope.paper_id,
                EducationKnowledgeScope.batch_id,
                EducationKnowledgeScope.created_at,
            )
        )
    ).all()
    return [_scope_out(item) for item in rows]


async def list_fact_scopes(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    agent_id: UUID,
    fact_id: UUID,
) -> list[EducationKnowledgeScopeOut]:
    rows = (
        await session.scalars(
            select(EducationKnowledgeScope)
            .where(
                EducationKnowledgeScope.tenant_id == tenant_id,
                EducationKnowledgeScope.workspace_id == workspace_id,
                EducationKnowledgeScope.agent_id == agent_id,
                EducationKnowledgeScope.fact_id == fact_id,
            )
            .order_by(
                EducationKnowledgeScope.course_id,
                EducationKnowledgeScope.curriculum_id,
                EducationKnowledgeScope.paper_id,
                EducationKnowledgeScope.batch_id,
                EducationKnowledgeScope.created_at,
            )
        )
    ).all()
    return [_scope_out(item) for item in rows]


async def replace_source_scopes(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    agent_id: UUID,
    source_id: UUID,
    pairs: Sequence[EducationKnowledgeScopeRef],
) -> list[EducationKnowledgeScopeOut]:
    normalized = await validate_scope_pairs(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        pairs=pairs,
    )
    await session.execute(
        delete(EducationKnowledgeScope).where(
            EducationKnowledgeScope.tenant_id == tenant_id,
            EducationKnowledgeScope.workspace_id == workspace_id,
            EducationKnowledgeScope.agent_id == agent_id,
            EducationKnowledgeScope.source_id == source_id,
        )
    )
    source_version_id = await session.scalar(
        select(EducationSourceVersion.id)
        .where(
            EducationSourceVersion.tenant_id == tenant_id,
            EducationSourceVersion.workspace_id == workspace_id,
            EducationSourceVersion.source_id == source_id,
        )
        .order_by(EducationSourceVersion.version.desc())
        .limit(1)
    )
    session.add_all(
        [
            EducationKnowledgeScope(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                agent_id=agent_id,
                source_id=source_id,
                source_version_id=source_version_id,
                course_id=pair.course_id,
                curriculum_id=pair.curriculum_id,
                paper_id=pair.paper_id,
                batch_id=pair.batch_id,
                selected_block_ids=pair.selected_block_ids,
                topic_ids=pair.topic_ids,
                material_type=pair.material_type,
                approval_status="draft",
                requires_release=True,
            )
            for pair in normalized
        ]
    )
    await session.flush()
    return await list_source_scopes(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        source_id=source_id,
    )


async def replace_fact_scopes(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    agent_id: UUID,
    fact_id: UUID,
    pairs: Sequence[EducationKnowledgeScopeRef],
) -> list[EducationKnowledgeScopeOut]:
    normalized = await validate_scope_pairs(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        pairs=pairs,
    )
    await session.execute(
        delete(EducationKnowledgeScope).where(
            EducationKnowledgeScope.tenant_id == tenant_id,
            EducationKnowledgeScope.workspace_id == workspace_id,
            EducationKnowledgeScope.agent_id == agent_id,
            EducationKnowledgeScope.fact_id == fact_id,
        )
    )
    session.add_all(
        [
            EducationKnowledgeScope(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                agent_id=agent_id,
                fact_id=fact_id,
                course_id=pair.course_id,
                curriculum_id=pair.curriculum_id,
                paper_id=pair.paper_id,
                batch_id=pair.batch_id,
                selected_block_ids=pair.selected_block_ids,
                topic_ids=pair.topic_ids,
                material_type=pair.material_type,
                approval_status="draft",
                requires_release=True,
            )
            for pair in normalized
        ]
    )
    await session.flush()
    return await list_fact_scopes(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        fact_id=fact_id,
    )
