from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import func, select

from northstar_api.agent_purpose import AgentPurpose
from northstar_api.config import get_settings
from northstar_api.database import SessionFactory
from northstar_api.education_conversation_context import EducationConversationContext
from northstar_api.education_knowledge_scope import EducationKnowledgeScope
from northstar_api.models import (
    Agent,
    Channel,
    Conversation,
    ConversationState,
    DocumentChunk,
    FactStatus,
    KnowledgeFact,
    KnowledgeKind,
    KnowledgeSource,
    KnowledgeStatus,
    Message,
)
from northstar_api.schemas import ChatStreamRequest
from northstar_api.services import education_chat
from northstar_api.services.education_chat import (
    EducationAwareChatCoordinator,
    EducationScopedRetrieval,
)
from northstar_api.services.retrieval import EducationRetrievalScope, RetrievalService

pytestmark = pytest.mark.usefixtures("crm_test_plan")


class FakeEmbeddingModel:
    async def embed_query(self, query: str) -> list[float]:
        del query
        return [1.0, 0.0]


class FakeGenerationModel:
    settings = SimpleNamespace(require_nvidia=False)

    async def generate_grounded(self, **kwargs):
        del kwargs
        return SimpleNamespace(content="Scoped answer")


class FakeRedis:
    async def check_rate_limit(self, *args, **kwargs):
        del args, kwargs
        return SimpleNamespace(allowed=True, retry_after=0)


@pytest.mark.asyncio
async def test_education_retrieval_forwards_ranking_limits(monkeypatch) -> None:
    observed: dict[str, object] = {}

    class BaseRetrieval:
        model = object()
        settings = object()

        async def retrieve(self, session, **kwargs):
            del session
            observed.update(kwargs)
            return []

    agent = SimpleNamespace(id=uuid.uuid4(), workspace_id=uuid.uuid4())

    class Session:
        async def scalar(self, statement):
            del statement
            return agent

    async def support_purpose(*args, **kwargs):
        del args, kwargs
        return AgentPurpose.SUPPORT

    monkeypatch.setattr(education_chat, "get_agent_purpose", support_purpose)
    retrieval = EducationScopedRetrieval(BaseRetrieval())  # type: ignore[arg-type]
    await retrieval.retrieve(
        Session(),  # type: ignore[arg-type]
        tenant_id=uuid.uuid4(),
        agent_id=agent.id,
        revision=3,
        query="What is CMA?",
        rerank_candidates=25,
        final_context_chunks=4,
    )

    assert observed["rerank_candidates"] == 25
    assert observed["final_context_chunks"] == 4


async def _workspace_headers(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> tuple[str, dict[str, str]]:
    response = await client.get("/api/v1/workspace", headers=auth_headers)
    assert response.status_code == 200, response.text
    workspace_id = response.json()["id"]
    return workspace_id, {**auth_headers, "X-Workspace-ID": workspace_id}


async def _course_batch(
    client: AsyncClient,
    headers: dict[str, str],
    seed: str,
) -> tuple[dict, dict]:
    course = await client.post(
        "/api/v1/education/courses",
        headers=headers,
        json={"code": f"RAG-{seed}", "name": f"RAG Course {seed}"},
    )
    assert course.status_code == 201, course.text
    batch = await client.post(
        "/api/v1/education/batches",
        headers=headers,
        json={
            "courseId": course.json()["id"],
            "code": f"RAG-{seed}-A",
            "name": f"RAG Batch {seed}",
            "startsOn": "2026-01-01",
            "endsOn": "2027-12-31",
        },
    )
    assert batch.status_code == 201, batch.text
    return course.json(), batch.json()


async def _education_agent(
    client: AsyncClient,
    headers: dict[str, str],
    seed: str,
) -> dict:
    response = await client.post(
        "/api/v1/agents",
        headers=headers,
        json={
            "name": f"Education RAG Agent {seed}",
            "description": "Scoped Education RAG acceptance agent",
            "purpose": "education",
            "deploymentChannel": "website",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _direct_source(
    *,
    tenant_id: uuid.UUID,
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    name: str,
    content: str,
) -> tuple[uuid.UUID, uuid.UUID]:
    async with SessionFactory() as session:
        source = KnowledgeSource(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            name=name,
            kind=KnowledgeKind.TEXT,
            status=KnowledgeStatus.READY,
            size_label="1 KB",
            content=content,
            checksum=uuid.uuid4().hex + uuid.uuid4().hex,
        )
        session.add(source)
        await session.flush()
        chunk = DocumentChunk(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            source_id=source.id,
            ordinal=0,
            content=content,
            token_count=max(1, len(content.split())),
            approved=True,
            revision=1,
            embedding=[1.0, 0.0],
            metadata_json={},
        )
        session.add(chunk)
        await session.commit()
        return source.id, chunk.id


async def test_education_knowledge_scope_api_validates_course_batch_and_agent_purpose(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    workspace_id, headers = await _workspace_headers(client, auth_headers)
    seed = uuid.uuid4().hex[:8].upper()
    course_a, batch_a = await _course_batch(client, headers, f"{seed}A")
    course_b, batch_b = await _course_batch(client, headers, f"{seed}B")
    agent = await _education_agent(client, headers, seed)

    async with SessionFactory() as session:
        agent_model = await session.scalar(select(Agent).where(Agent.id == uuid.UUID(agent["id"])))
        assert agent_model is not None
        tenant_id = agent_model.tenant_id

    source_id, _ = await _direct_source(
        tenant_id=tenant_id,
        workspace_id=uuid.UUID(workspace_id),
        agent_id=uuid.UUID(agent["id"]),
        name=f"Scoped Source {seed}",
        content="alpha authorized knowledge",
    )
    saved = await client.put(
        f"/api/v1/knowledge/{source_id}/education-scopes",
        headers=headers,
        json={"scopes": [{"courseId": course_a["id"], "batchId": batch_a["id"]}]},
    )
    assert saved.status_code == 200, saved.text
    assert len(saved.json()) == 1
    assert saved.json()[0]["courseId"] == course_a["id"]
    assert saved.json()[0]["batchId"] == batch_a["id"]

    listed = await client.get(
        f"/api/v1/knowledge/{source_id}/education-scopes",
        headers=headers,
    )
    assert listed.status_code == 200, listed.text
    assert listed.json() == saved.json()

    wrong_pair = await client.put(
        f"/api/v1/knowledge/{source_id}/education-scopes",
        headers=headers,
        json={"scopes": [{"courseId": course_a["id"], "batchId": batch_b["id"]}]},
    )
    assert wrong_pair.status_code == 422, wrong_pair.text

    duplicate = await client.put(
        f"/api/v1/knowledge/{source_id}/education-scopes",
        headers=headers,
        json={
            "scopes": [
                {"courseId": course_a["id"], "batchId": batch_a["id"]},
                {"courseId": course_a["id"], "batchId": batch_a["id"]},
            ]
        },
    )
    assert duplicate.status_code == 422, duplicate.text

    support = await client.post(
        "/api/v1/agents",
        headers=headers,
        json={
            "name": f"Support RAG Agent {seed}",
            "description": "Compatibility agent",
            "purpose": "support",
            "deploymentChannel": "website",
        },
    )
    assert support.status_code == 201, support.text
    support_source_id, _ = await _direct_source(
        tenant_id=tenant_id,
        workspace_id=uuid.UUID(workspace_id),
        agent_id=uuid.UUID(support.json()["id"]),
        name=f"Support Source {seed}",
        content="normal support knowledge",
    )
    rejected = await client.put(
        f"/api/v1/knowledge/{support_source_id}/education-scopes",
        headers=headers,
        json={"scopes": [{"courseId": course_b["id"], "batchId": batch_b["id"]}]},
    )
    assert rejected.status_code == 409, rejected.text


async def test_course_aware_upload_requires_approved_active_release(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    workspace_id, headers = await _workspace_headers(client, auth_headers)
    seed = uuid.uuid4().hex[:8].upper()
    course, batch = await _course_batch(client, headers, seed)
    agent = await _education_agent(client, headers, seed)

    created = await client.post(
        f"/api/v1/agents/{agent['id']}/knowledge",
        headers=headers,
        json={
            "name": f"Course-aware source {seed}",
            "kind": "text",
            "content": "alpha release-gated education evidence",
            "educationDestination": {
                "courseId": course["id"],
                "curriculumId": batch["curriculumId"],
                "batchId": batch["id"],
                "materialType": "notes",
            },
        },
    )
    assert created.status_code == 201, created.text
    source_id = created.json()["id"]

    scopes = await client.get(
        f"/api/v1/knowledge/{source_id}/education-scopes",
        headers=headers,
    )
    assert scopes.status_code == 200, scopes.text
    assignment = scopes.json()[0]
    assert assignment["approvalStatus"] == "draft"
    assert assignment["requiresRelease"] is True
    assert assignment["sourceVersionId"] is not None

    stale = await client.post(
        f"/api/v1/knowledge/education-assignments/{assignment['id']}/approve",
        headers=headers,
        json={"extractionRevision": 2, "mappingRevision": 1},
    )
    assert stale.status_code == 409, stale.text

    approved = await client.post(
        f"/api/v1/knowledge/education-assignments/{assignment['id']}/approve",
        headers=headers,
        json={"extractionRevision": 1, "mappingRevision": 1},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["approvalStatus"] == "approved"

    release = await client.post(
        "/api/v1/education/knowledge/releases",
        headers=headers,
        json={
            "agentId": agent["id"],
            "courseId": course["id"],
            "curriculumId": batch["curriculumId"],
            "assignmentIds": [assignment["id"]],
        },
    )
    assert release.status_code == 201, release.text
    assert release.json()["status"] == "candidate"

    activated = await client.post(
        f"/api/v1/education/knowledge/releases/{release.json()['id']}/activate",
        headers=headers,
        json={"indexVerified": True},
    )
    assert activated.status_code == 200, activated.text
    assert activated.json()["status"] == "active"

    async with SessionFactory() as session:
        agent_model = await session.scalar(select(Agent).where(Agent.id == uuid.UUID(agent["id"])))
        assert agent_model is not None
        results = await RetrievalService(
            model=FakeEmbeddingModel(), settings=get_settings()  # type: ignore[arg-type]
        ).retrieve(
            session,
            tenant_id=agent_model.tenant_id,
            agent_id=agent_model.id,
            revision=1,
            query="alpha",
            education_scope=EducationRetrievalScope(
                workspace_id=uuid.UUID(workspace_id),
                student_id=uuid.uuid4(),
                enrollment_id=uuid.uuid4(),
                course_id=uuid.UUID(course["id"]),
                batch_id=uuid.UUID(batch["id"]),
                curriculum_id=uuid.UUID(batch["curriculumId"]),
            ),
        )
    assert source_id in {item.source_id for item in results}


async def test_existing_retrieval_filters_chunks_and_facts_by_education_scope(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    workspace_id, headers = await _workspace_headers(client, auth_headers)
    seed = uuid.uuid4().hex[:8].upper()
    course_a, batch_a = await _course_batch(client, headers, f"{seed}A")
    course_b, batch_b = await _course_batch(client, headers, f"{seed}B")
    agent = await _education_agent(client, headers, seed)

    async with SessionFactory() as session:
        agent_model = await session.scalar(select(Agent).where(Agent.id == uuid.UUID(agent["id"])))
        assert agent_model is not None
        tenant_id = agent_model.tenant_id

    source_a, chunk_a = await _direct_source(
        tenant_id=tenant_id,
        workspace_id=uuid.UUID(workspace_id),
        agent_id=uuid.UUID(agent["id"]),
        name=f"CPA {seed}",
        content="alpha cpa private syllabus",
    )
    source_b, chunk_b = await _direct_source(
        tenant_id=tenant_id,
        workspace_id=uuid.UUID(workspace_id),
        agent_id=uuid.UUID(agent["id"]),
        name=f"CMA {seed}",
        content="alpha cma private syllabus",
    )
    source_unscoped, chunk_unscoped = await _direct_source(
        tenant_id=tenant_id,
        workspace_id=uuid.UUID(workspace_id),
        agent_id=uuid.UUID(agent["id"]),
        name=f"Unscoped {seed}",
        content="alpha unscoped private syllabus",
    )

    async with SessionFactory() as session:
        fact_direct = KnowledgeFact(
            tenant_id=tenant_id,
            workspace_id=uuid.UUID(workspace_id),
            agent_id=uuid.UUID(agent["id"]),
            question="alpha direct fact",
            answer="alpha direct answer",
            status=FactStatus.APPROVED,
            priority=0,
            revision=1,
            embedding=[1.0, 0.0],
        )
        fact_inherited = KnowledgeFact(
            tenant_id=tenant_id,
            workspace_id=uuid.UUID(workspace_id),
            agent_id=uuid.UUID(agent["id"]),
            source_id=source_a,
            question="alpha inherited fact",
            answer="alpha inherited answer",
            status=FactStatus.APPROVED,
            priority=0,
            revision=1,
            embedding=[1.0, 0.0],
        )
        fact_other = KnowledgeFact(
            tenant_id=tenant_id,
            workspace_id=uuid.UUID(workspace_id),
            agent_id=uuid.UUID(agent["id"]),
            source_id=source_b,
            question="alpha other fact",
            answer="alpha other answer",
            status=FactStatus.APPROVED,
            priority=0,
            revision=1,
            embedding=[1.0, 0.0],
        )
        fact_unscoped = KnowledgeFact(
            tenant_id=tenant_id,
            workspace_id=uuid.UUID(workspace_id),
            agent_id=uuid.UUID(agent["id"]),
            question="alpha unscoped fact",
            answer="alpha unscoped answer",
            status=FactStatus.APPROVED,
            priority=0,
            revision=1,
            embedding=[1.0, 0.0],
        )
        session.add_all([fact_direct, fact_inherited, fact_other, fact_unscoped])
        await session.flush()
        session.add_all(
            [
                EducationKnowledgeScope(
                    tenant_id=tenant_id,
                    workspace_id=uuid.UUID(workspace_id),
                    agent_id=uuid.UUID(agent["id"]),
                    source_id=source_a,
                    course_id=uuid.UUID(course_a["id"]),
                    batch_id=uuid.UUID(batch_a["id"]),
                ),
                EducationKnowledgeScope(
                    tenant_id=tenant_id,
                    workspace_id=uuid.UUID(workspace_id),
                    agent_id=uuid.UUID(agent["id"]),
                    source_id=source_b,
                    course_id=uuid.UUID(course_b["id"]),
                    batch_id=uuid.UUID(batch_b["id"]),
                ),
                EducationKnowledgeScope(
                    tenant_id=tenant_id,
                    workspace_id=uuid.UUID(workspace_id),
                    agent_id=uuid.UUID(agent["id"]),
                    fact_id=fact_direct.id,
                    course_id=uuid.UUID(course_a["id"]),
                    batch_id=uuid.UUID(batch_a["id"]),
                ),
            ]
        )
        await session.commit()
        fact_direct_id = fact_direct.id
        fact_inherited_id = fact_inherited.id
        fact_other_id = fact_other.id
        fact_unscoped_id = fact_unscoped.id

    retrieval = RetrievalService(model=FakeEmbeddingModel(), settings=get_settings())  # type: ignore[arg-type]
    education_scope = EducationRetrievalScope(
        workspace_id=uuid.UUID(workspace_id),
        student_id=uuid.uuid4(),
        enrollment_id=uuid.uuid4(),
        course_id=uuid.UUID(course_a["id"]),
        batch_id=uuid.UUID(batch_a["id"]),
    )
    async with SessionFactory() as session:
        scoped = await retrieval.retrieve(
            session,
            tenant_id=tenant_id,
            agent_id=uuid.UUID(agent["id"]),
            revision=1,
            query="alpha",
            education_scope=education_scope,
        )
        unscoped = await retrieval.retrieve(
            session,
            tenant_id=tenant_id,
            agent_id=uuid.UUID(agent["id"]),
            revision=1,
            query="alpha",
        )

    scoped_ids = {item.entity_id for item in scoped}
    assert str(chunk_a) in scoped_ids
    assert str(fact_direct_id) in scoped_ids
    assert str(fact_inherited_id) in scoped_ids
    assert str(chunk_b) not in scoped_ids
    assert str(chunk_unscoped) not in scoped_ids
    assert str(fact_other_id) not in scoped_ids
    assert str(fact_unscoped_id) not in scoped_ids
    assert str(chunk_b) in {item.entity_id for item in unscoped}
    assert str(chunk_unscoped) in {item.entity_id for item in unscoped}
    assert str(fact_other_id) in {item.entity_id for item in unscoped}
    assert str(fact_unscoped_id) in {item.entity_id for item in unscoped}
    assert source_unscoped is not None


async def test_education_chat_requires_current_authorized_context_before_reservation(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    workspace_id, headers = await _workspace_headers(client, auth_headers)
    seed = uuid.uuid4().hex[:8].upper()
    course, batch = await _course_batch(client, headers, seed)
    student = await client.post(
        "/api/v1/education/students",
        headers=headers,
        json={"studentNumber": f"RAG-{seed}", "name": f"RAG Student {seed}"},
    )
    assert student.status_code == 201, student.text
    agent = await _education_agent(client, headers, seed)
    enrollment = await client.post(
        "/api/v1/education/enrollments",
        headers=headers,
        json={
            "studentId": student.json()["id"],
            "courseId": course["id"],
            "batchId": batch["id"],
            "agentId": agent["id"],
            "status": "active",
            "startsOn": "2026-01-01",
            "endsOn": "2027-12-31",
        },
    )
    assert enrollment.status_code == 201, enrollment.text
    activated = await client.patch(
        f"/api/v1/agents/{agent['id']}",
        headers=headers,
        json={"status": "active"},
    )
    assert activated.status_code == 200, activated.text

    async with SessionFactory() as session:
        agent_model = await session.scalar(select(Agent).where(Agent.id == uuid.UUID(agent["id"])))
        assert agent_model is not None
        tenant_id = agent_model.tenant_id
        conversation = Conversation(
            tenant_id=tenant_id,
            workspace_id=uuid.UUID(workspace_id),
            agent_id=uuid.UUID(agent["id"]),
            visitor_id=f"rag:{seed}",
            visitor_name="RAG Student",
            channel=Channel.WIDGET,
            state=ConversationState.OPEN,
            knowledge_revision=1,
        )
        session.add(conversation)
        await session.flush()
        session.add(
            EducationConversationContext(
                tenant_id=tenant_id,
                workspace_id=uuid.UUID(workspace_id),
                conversation_id=conversation.id,
                agent_id=uuid.UUID(agent["id"]),
                student_id=uuid.UUID(student.json()["id"]),
                enrollment_id=uuid.UUID(enrollment.json()["id"]),
                course_id=uuid.UUID(course["id"]),
                batch_id=uuid.UUID(batch["id"]),
            )
        )
        await session.commit()
        conversation_id = conversation.id

    coordinator = EducationAwareChatCoordinator(
        retrieval=EducationScopedRetrieval(
            RetrievalService(model=FakeEmbeddingModel(), settings=get_settings())  # type: ignore[arg-type]
        ),
        model=FakeGenerationModel(),  # type: ignore[arg-type]
        redis=FakeRedis(),  # type: ignore[arg-type]
    )

    with pytest.raises(HTTPException) as missing:
        async with SessionFactory() as session:
            await coordinator.prepare(
                session,
                tenant_id=tenant_id,
                workspace_id=uuid.UUID(workspace_id),
                request=ChatStreamRequest(agent_id=agent["id"], message="alpha"),
            )
    assert missing.value.status_code == 403

    suspended = await client.patch(
        f"/api/v1/education/enrollments/{enrollment.json()['id']}",
        headers=headers,
        json={"status": "suspended"},
    )
    assert suspended.status_code == 200, suspended.text

    async with SessionFactory() as session:
        before = int(
            await session.scalar(
                select(func.count(Message.id)).where(Message.conversation_id == conversation_id)
            )
            or 0
        )
    with pytest.raises(HTTPException) as stale:
        async with SessionFactory() as session:
            await coordinator.prepare(
                session,
                tenant_id=tenant_id,
                workspace_id=uuid.UUID(workspace_id),
                request=ChatStreamRequest(
                    agent_id=agent["id"],
                    conversation_id=conversation_id,
                    message="alpha",
                ),
            )
    assert stale.value.status_code == 403
    async with SessionFactory() as session:
        after = int(
            await session.scalar(
                select(func.count(Message.id)).where(Message.conversation_id == conversation_id)
            )
            or 0
        )
    assert after == before
