"""Idempotent index preparation on the existing ingestion worker queue."""
from __future__ import annotations

import asyncio
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker

from northstar_api.config import get_settings
from northstar_api.course_knowledge_models import CourseMaterialAssignment
from northstar_api.database import build_engine, set_tenant_context, tenant_context
from northstar_api.services.course_knowledge import Boundary, prepare_assignment_index, scoped_row
from northstar_api.services.course_knowledge_policy import KnowledgePolicyError
from northstar_api.workers.celery_app import celery_app


async def prepare_index(tenant_id: str, workspace_id: str, agent_id: str, assignment_id: str, revision: int) -> None:
    boundary = Boundary(UUID(tenant_id), UUID(workspace_id), UUID(agent_id))
    settings = get_settings()
    engine = build_engine(settings, apply_runtime_role=settings.is_postgres and settings.database_apply_runtime_role and not settings.app_auto_create_schema)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    token = tenant_context.set(str(boundary.tenant_id))
    try:
        async with factory() as session:
            await set_tenant_context(session, boundary.tenant_id)
            try:
                await prepare_assignment_index(session, boundary, UUID(assignment_id), revision)
                await session.commit()
            except Exception as exc:
                await session.rollback()
                assignment = await scoped_row(session, CourseMaterialAssignment, UUID(assignment_id), boundary, lock=True)
                if assignment.revision == revision and assignment.index_status != "ready":
                    assignment.index_status = "failed"
                    assignment.index_error = str(exc)[:500] if isinstance(exc, KnowledgePolicyError) else f"Index preparation failed ({type(exc).__name__}); retry this revision"
                    await session.commit()
                if isinstance(exc, KnowledgePolicyError):
                    return  # A new review/revision, not repeated provider calls, is required.
                raise
    finally:
        tenant_context.reset(token)
        await engine.dispose()


@celery_app.task(name="northstar.prepare_course_assignment", autoretry_for=(Exception,), retry_backoff=True, retry_backoff_max=300, retry_jitter=True, max_retries=5)
def prepare_course_assignment(tenant_id: str, workspace_id: str, agent_id: str, assignment_id: str, revision: int) -> None:
    asyncio.run(prepare_index(tenant_id, workspace_id, agent_id, assignment_id, revision))
