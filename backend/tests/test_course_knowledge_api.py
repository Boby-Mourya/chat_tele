"""Database/API acceptance tests. Use the repository's real app and fixtures.

Model calls are deterministic test doubles; these tests do not certify NVIDIA,
object storage, WhatsApp delivery, or PostgreSQL concurrency in production.
"""

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from test_education_runtime_authorization import (
    _create_agent,
    _create_batch,
    _create_course,
    _create_enrollment,
    _create_identity,
    _create_student,
    _workspace_headers,
)

from northstar_api.config import get_settings
from northstar_api.database import SessionFactory
from northstar_api.models import Agent, AgentStatus, IngestionJob, KnowledgeSource
from northstar_api.services.llm import nvidia_adapter

pytestmark = pytest.mark.usefixtures("crm_test_plan")


async def call(client, headers, method, path, body=None, expected=200):
    result = await client.request(
        method, "/api/v1" + path, headers=headers, **({"json": body} if body is not None else {})
    )
    assert result.status_code == expected, result.text
    return result.json()


@pytest.fixture
async def course_setup(client, auth_headers, monkeypatch):
    async def documents(texts):
        return [[1.0] + [0.0] * (get_settings().embedding_dimension - 1) for _ in texts]

    async def query(text):
        return (await documents([text]))[0]

    async def generated(**kwargs):
        return SimpleNamespace(content="Teacher-review draft from the explicitly selected evidence. [S1]")

    monkeypatch.setattr(nvidia_adapter, "embed_documents", documents)
    monkeypatch.setattr(nvidia_adapter, "embed_query", query)
    monkeypatch.setattr(nvidia_adapter, "generate_grounded", generated)
    _, headers = await _workspace_headers(client, auth_headers)
    suffix = uuid4().hex[:10]
    agent = await _create_agent(client, headers, name="Course release " + suffix)
    student = await _create_student(client, headers, "ST-" + suffix)
    phone = "+919" + str(int(suffix, 16) % 1000000000).zfill(9)
    await _create_identity(
        client, headers, student_id=student["id"], identity_type="whatsapp", identifier=phone
    )
    course = await _create_course(client, headers, "CMA-" + suffix)
    batch = await _create_batch(client, headers, course_id=course["id"], code="B-" + suffix)
    enrollment = await _create_enrollment(
        client,
        headers,
        student_id=student["id"],
        course_id=course["id"],
        batch_id=batch["id"],
        agent_id=agent["id"],
    )
    curriculum = await call(
        client,
        headers,
        "POST",
        "/education/knowledge/curricula",
        {"courseId": course["id"], "code": "2026", "name": "Reviewed 2026 curriculum"},
        201,
    )
    papers = []
    for code in ("P1", "P2"):
        papers.append(
            await call(
                client,
                headers,
                "POST",
                "/education/knowledge/papers",
                {"curriculumId": curriculum["id"], "code": code, "name": "Paper " + code},
                201,
            )
        )
    await call(
        client,
        headers,
        "PUT",
        "/education/knowledge/batch-curriculum",
        {"batchId": batch["id"], "curriculumId": curriculum["id"]},
    )
    prefix = f"/agents/{agent['id']}/education-knowledge"
    await call(
        client,
        headers,
        "PUT",
        prefix + f"/enrollments/{enrollment['id']}/access",
        {
            "curriculumId": curriculum["id"],
            "paperIds": [papers[0]["id"]],
            "selectedPaperId": papers[0]["id"],
            "expectedRevision": 0,
        },
    )
    async with SessionFactory() as session:
        entity = await session.get(Agent, UUID(agent["id"]))
        entity.status = AgentStatus.ACTIVE
        await session.commit()
    return dict(
        headers=headers,
        agent=agent,
        course=course,
        batch=batch,
        student=student,
        enrollment=enrollment,
        curriculum=curriculum,
        papers=papers,
        prefix=prefix,
        phone=phone,
    )


async def source_assignment(client, setup):
    h, p = setup["headers"], setup["prefix"]
    body = {
        "idempotencyKey": str(uuid4()),
        "title": "Mixed paper source",
        "kind": "text",
        "content": "Paper A approved lesson\n\nPaper B PRIVATE_SECRET",
        "destination": {
            "courseId": setup["course"]["id"],
            "curriculumId": setup["curriculum"]["id"],
            "mixedPapers": True,
        },
    }
    first = await call(client, h, "POST", p + "/uploads", body, 201)
    repeated = await call(client, h, "POST", p + "/uploads", body, 201)
    assert first["sourceId"] == repeated["sourceId"]
    version = await call(client, h, "POST", p + f"/sources/{first['sourceId']}/snapshot", expected=201)
    detail = await call(client, h, "GET", p + f"/versions/{version['id']}")
    body = {
        "idempotencyKey": str(uuid4()),
        "sourceVersionId": version["id"],
        "courseId": setup["course"]["id"],
        "curriculumId": setup["curriculum"]["id"],
        "paperId": setup["papers"][0]["id"],
        "blockIds": [detail["blocks"][0]["id"]],
    }
    assignment = await call(client, h, "POST", p + "/assignments", body, 201)
    return version, assignment, body


async def publish(client, setup, version, assignment):
    h, p = setup["headers"], setup["prefix"]
    await call(
        client,
        h,
        "POST",
        p + f"/assignments/{assignment['id']}/approve",
        {
            "expectedRevision": assignment["revision"],
            "expectedSourceHash": version["recordHash"],
            "reason": "Compared original content and confirmed Paper P1 audience",
        },
    )
    for _ in range(2):
        row = await call(
            client,
            h,
            "POST",
            p + f"/assignments/{assignment['id']}/prepare",
            {"expectedRevision": assignment["revision"]},
            202,
        )
        assert row["indexStatus"] == "ready"
    candidate = await call(
        client,
        h,
        "POST",
        p + "/releases",
        {
            "courseId": setup["course"]["id"],
            "curriculumId": setup["curriculum"]["id"],
            "assignmentIds": [assignment["id"]],
        },
        201,
    )
    head = await call(
        client,
        h,
        "POST",
        p + f"/releases/{candidate['id']}/publish",
        {"expectedEpoch": candidate["expectedEpoch"]},
    )
    retry = await call(
        client,
        h,
        "POST",
        p + f"/releases/{candidate['id']}/publish",
        {"expectedEpoch": candidate["expectedEpoch"]},
    )
    assert retry["epoch"] == head["epoch"]
    return candidate, head


async def test_release_lifecycle_scoped_preview_and_withdrawal(client, course_setup):
    s = course_setup
    h, p = s["headers"], s["prefix"]
    version, assignment, _ = await source_assignment(client, s)
    preview = {
        "enrollmentId": s["enrollment"]["id"],
        "query": "lesson",
        "selectedPaperId": s["papers"][0]["id"],
    }
    unpublished = await call(client, h, "POST", p + "/preview", preview)
    assert unpublished["evidence"] == []
    await publish(client, s, version, assignment)
    result = await call(client, h, "POST", p + "/preview", preview)
    assert result["evidence"] and all("PRIVATE_SECRET" not in e["text"] for e in result["evidence"])
    assert all(e["metadata"]["assignment_id"] == assignment["id"] for e in result["evidence"])
    await call(client, h, "POST", p + "/preview", {**preview, "selectedPaperId": s["papers"][1]["id"]}, 409)
    overview = await call(client, h, "POST", p + "/preview", {**preview, "selectedPaperId": None})
    assert overview["evidence"] == []
    entry = result["evidence"][0]["entity_id"]
    excerpt = await client.post("/api/v1" + p + f"/preview/excerpts/{entry}", headers=h, json=preview)
    assert excerpt.status_code == 200 and "PRIVATE_SECRET" not in excerpt.text
    await call(
        client,
        h,
        "POST",
        p + f"/versions/{version['id']}/withdraw",
        {"reason": "Source withdrawn by teacher"},
    )
    assert (await call(client, h, "POST", p + "/preview", preview))["evidence"] == []
    revoked = await client.post("/api/v1" + p + f"/preview/excerpts/{entry}", headers=h, json=preview)
    assert revoked.status_code == 404


async def test_changed_mapping_invalidates_approval_and_failed_candidate_preserves_head(client, course_setup):
    s = course_setup
    h, p = s["headers"], s["prefix"]
    version, assignment, body = await source_assignment(client, s)
    _, old_head = await publish(client, s, version, assignment)
    await call(
        client,
        h,
        "POST",
        p + "/releases",
        {
            "courseId": s["course"]["id"],
            "curriculumId": s["curriculum"]["id"],
            "assignmentIds": [str(uuid4())],
        },
        409,
    )
    current = await call(client, h, "GET", p + "/status")
    assert (
        next(row for row in current["heads"] if row["id"] == old_head["id"])["releaseId"]
        == old_head["releaseId"]
    )
    changed = await call(
        client,
        h,
        "PUT",
        p + f"/assignments/{assignment['id']}",
        {**body, "expectedRevision": assignment["revision"], "batchId": s["batch"]["id"]},
    )
    assert changed["status"] == "review" and changed["approvalFingerprint"] is None
    await call(
        client,
        h,
        "POST",
        p + f"/assignments/{assignment['id']}/approve",
        {
            "expectedRevision": assignment["revision"],
            "expectedSourceHash": version["recordHash"],
            "reason": "Stale review must fail",
        },
        409,
    )


async def test_course_selection_does_not_enqueue_processing(client, course_setup):
    from northstar_api.education_student_identities import StudentIdentityType
    from northstar_api.services.course_study_access import authorize_study_access
    from northstar_api.services.education_runtime_authorization import EducationIdentityCandidate

    s = course_setup
    other = await _create_course(client, s["headers"], "CPA-" + uuid4().hex[:10])
    batch = await _create_batch(client, s["headers"], course_id=other["id"], code="CPA-B-" + uuid4().hex[:8])
    enrolled = await _create_enrollment(
        client,
        s["headers"],
        student_id=s["student"]["id"],
        course_id=other["id"],
        batch_id=batch["id"],
        agent_id=s["agent"]["id"],
    )
    curriculum = await call(
        client,
        s["headers"],
        "POST",
        "/education/knowledge/curricula",
        {"courseId": other["id"], "code": "2026", "name": "CPA 2026"},
        201,
    )
    paper = await call(
        client,
        s["headers"],
        "POST",
        "/education/knowledge/papers",
        {"curriculumId": curriculum["id"], "code": "CPA1", "name": "CPA paper"},
        201,
    )
    await call(
        client,
        s["headers"],
        "PUT",
        "/education/knowledge/batch-curriculum",
        {"batchId": batch["id"], "curriculumId": curriculum["id"]},
    )
    await call(
        client,
        s["headers"],
        "PUT",
        s["prefix"] + f"/enrollments/{enrolled['id']}/access",
        {"curriculumId": curriculum["id"], "paperIds": [paper["id"]], "expectedRevision": 0},
    )
    identity = EducationIdentityCandidate(StudentIdentityType.WHATSAPP, s["phone"])
    async with SessionFactory() as session:
        agent = await session.get(Agent, UUID(s["agent"]["id"]))
        job_count = (
            select(func.count())
            .select_from(IngestionJob)
            .join(KnowledgeSource, KnowledgeSource.id == IngestionJob.source_id)
            .where(KnowledgeSource.agent_id == agent.id)
        )
        before = await session.scalar(job_count)
        kwargs = dict(
            tenant_id=agent.tenant_id, workspace_id=agent.workspace_id, agent=agent, identity=identity
        )
        decision, prompt = await authorize_study_access(
            session, **kwargs, message="course " + s["course"]["code"]
        )
        assert decision.authorized and prompt
        await session.commit()
        decision, prompt = await authorize_study_access(session, **kwargs, message="paper P1")
        assert decision.course_id == UUID(s["course"]["id"]) and prompt
        await session.commit()
        decision, prompt = await authorize_study_access(session, **kwargs, message="Explain this lesson")
        assert decision.authorized and prompt is None
        decision, prompt = await authorize_study_access(session, **kwargs, message="course " + other["code"])
        assert decision.authorized and decision.course_id == UUID(other["id"]) and prompt
        await session.commit()
        decision, prompt = await authorize_study_access(session, **kwargs, message="paper CPA1")
        assert decision.enrollment_id == UUID(enrolled["id"]) and prompt
        assert await session.scalar(job_count) == before


async def test_legacy_education_upload_requires_explicit_destination(client, course_setup):
    s = course_setup
    await call(
        client,
        s["headers"],
        "POST",
        f"/agents/{s['agent']['id']}/knowledge",
        {"kind": "text", "name": "Unassigned normal upload", "content": "Must not start processing"},
        409,
    )


async def test_practice_attempts_are_idempotent_and_update_scoped_progress(client, course_setup):
    s = course_setup
    payload = {
        "agentId": s["agent"]["id"],
        "studentId": s["student"]["id"],
        "enrollmentId": s["enrollment"]["id"],
        "paperId": s["papers"][0]["id"],
        "idempotencyKey": "practice-" + uuid4().hex,
        "question": "What is 2 + 2?",
        "answerKey": "4",
    }
    first = await call(client, s["headers"], "POST", "/education/practice/attempts", payload, 201)
    repeated = await call(client, s["headers"], "POST", "/education/practice/attempts", payload, 201)
    assert repeated["id"] == first["id"]

    answered = await call(
        client,
        s["headers"],
        "POST",
        f"/education/practice/attempts/{first['id']}/submit",
        {"studentAnswer": "4"},
    )
    assert answered["isCorrect"] is True

    progress = await call(
        client,
        s["headers"],
        "GET",
        f"/education/progress?enrollment_id={s['enrollment']['id']}&paper_id={s['papers'][0]['id']}",
    )
    assert len(progress) == 1
    assert progress[0]["practiceAttempts"] == 1
    assert progress[0]["objectiveAnswersCorrect"] == 1
    assert progress[0]["objectiveAnswersGraded"] == 1
