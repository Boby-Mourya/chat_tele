"""API state transitions, revision races, immutable evidence, and indexing barriers."""

import hashlib
import io
import zipfile
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from northstar_api.config import Settings
from northstar_api.models import JobStatus, KnowledgeKind, KnowledgeSource, KnowledgeStatus
from northstar_api.routers import knowledge
from northstar_api.services import ingestion
from northstar_api.services.hybrid_extraction import ExtractionPackage, extract_document


@pytest.fixture
async def review_context(monkeypatch):
    raw = b"Value -12.50\r\n"
    settings = Settings(_env_file=None, background_dispatch_enabled=True)
    package = await extract_document(raw, "source.txt", settings)
    package.record["extraction_revision"] = 1
    source = KnowledgeSource(
        id=uuid4(),
        tenant_id=uuid4(),
        workspace_id=uuid4(),
        agent_id=uuid4(),
        name="source.txt",
        kind=KnowledgeKind.FILE,
        status=KnowledgeStatus.NEEDS_REVIEW,
        checksum=hashlib.sha256(raw).hexdigest(),
        revision=1,
        chunk_count=0,
        size_label="1 unit",
        updated_at=datetime.now(UTC),
        object_key="knowledge/source.txt",
    )
    prefix = f"extractions/{source.tenant_id}/{source.id}/"
    source.extraction_key = prefix + "v0001.zip"
    archives = {source.extraction_key: package.archive()}

    async def download(key, **kwargs):
        return archives[key], {}

    async def put(tenant, source_id, data, version):
        key = prefix + f"v{version:04d}.zip"
        archives[key] = data
        return key

    store = SimpleNamespace(
        download=AsyncMock(side_effect=download), put_extraction=AsyncMock(side_effect=put)
    )
    monkeypatch.setattr(knowledge, "object_store", store)
    monkeypatch.setattr(knowledge, "_review_source", AsyncMock(return_value=source))
    monkeypatch.setattr(knowledge, "get_settings", lambda: settings)
    monkeypatch.setattr(knowledge, "enqueue_event", lambda *a, **k: None)
    added = []
    session = SimpleNamespace(commit=AsyncMock(), add=added.append)
    return SimpleNamespace(
        source=source, raw=raw, store=store, archives=archives, session=session, added=added
    )


def approval(revision):
    return knowledge.ExtractionApproval.model_validate(
        {
            "extractionRevision": revision,
            "pages": [
                {
                    "number": 1,
                    "selectedText": "Value -12.50\r\n",
                    "reason": "Compared source bytes",
                    "structureConfirmed": True,
                    "blankConfirmed": False,
                    "blocks": [],
                }
            ],
            "issueResolutions": [],
        }
    )


async def test_second_reviewer_releases_correct_version(review_context):
    c = review_context
    alice, bob = SimpleNamespace(user_id=uuid4()), SimpleNamespace(user_id=uuid4())
    first = await knowledge.approve_extraction(c.source.id, approval(1), alice, c.session)
    assert first.status == KnowledgeStatus.NEEDS_REVIEW
    assert c.source.revision == 2 and not c.added and c.source.content is None
    with pytest.raises(HTTPException) as stale:
        await knowledge.approve_extraction(c.source.id, approval(1), bob, c.session)
    assert stale.value.status_code == 409
    await knowledge.approve_extraction(c.source.id, approval(2), alice, c.session)
    assert c.source.status == KnowledgeStatus.NEEDS_REVIEW
    await knowledge.approve_extraction(c.source.id, approval(3), bob, c.session)
    assert c.source.revision == 4
    assert c.source.status == KnowledgeStatus.PROCESSING
    assert c.source.content == c.raw.decode()
    assert len(c.added) == 1
    final = ExtractionPackage.from_archive(
        c.archives[c.source.extraction_key], source_sha256=c.source.checksum, revision=4
    )
    assert final.record["release_eligible"] and final.record["review_status"] == "verified_release"
    assert len(c.archives) == 4
    assert c.store.put_extraction.await_count == 3


async def test_corrupted_archive_rejected(review_context):
    c = review_context
    payload = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(c.archives[c.source.extraction_key])) as archive:
        with zipfile.ZipFile(payload, "w") as altered:
            for name in archive.namelist():
                altered.writestr(name, b"{}" if name == "extracted.json" else archive.read(name))
    c.archives[c.source.extraction_key] = payload.getvalue()
    with pytest.raises(HTTPException) as failure:
        await knowledge._load_extraction(c.source)
    assert failure.value.status_code == 409


async def test_file_text_cannot_bypass_verified_release(review_context, monkeypatch):
    c = review_context
    c.source.content = "unreviewed content"
    job = SimpleNamespace(status=JobStatus.QUEUED, attempts=0)
    session = SimpleNamespace(scalar=AsyncMock(side_effect=[c.source, job]), commit=AsyncMock())
    embed = AsyncMock()
    monkeypatch.setattr(ingestion, "object_store", c.store)
    monkeypatch.setattr(ingestion.nvidia_adapter, "embed_documents", embed)
    with pytest.raises(ValueError, match="verified release"):
        await ingestion.ingest_source_async(session, c.source.id)
    embed.assert_not_awaited()
    assert c.source.status == KnowledgeStatus.FAILED


async def test_post_review_tampering_never_embeds(review_context, monkeypatch):
    c = review_context
    await knowledge.approve_extraction(c.source.id, approval(1), SimpleNamespace(user_id=uuid4()), c.session)
    await knowledge.approve_extraction(c.source.id, approval(2), SimpleNamespace(user_id=uuid4()), c.session)
    c.source.content = "tampered indexing text"
    job = SimpleNamespace(status=JobStatus.QUEUED, attempts=0)
    session = SimpleNamespace(scalar=AsyncMock(side_effect=[c.source, job]), commit=AsyncMock())
    embed = AsyncMock()
    monkeypatch.setattr(ingestion, "object_store", c.store)
    monkeypatch.setattr(ingestion.nvidia_adapter, "embed_documents", embed)
    with pytest.raises(ValueError, match="differs from verified"):
        await ingestion.ingest_source_async(session, c.source.id)
    embed.assert_not_awaited()


async def test_manifest_accounts_for_extra_artifacts(review_context):
    c = review_context
    with zipfile.ZipFile(io.BytesIO(c.archives[c.source.extraction_key])) as archive:
        entries = {n: archive.read(n) for n in archive.namelist()}
    entries["unexpected.txt"] = b"not in manifest"
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as z:
        for name, value in entries.items():
            z.writestr(name, value)
    with pytest.raises(ValueError, match="every artifact"):
        ExtractionPackage.from_archive(output.getvalue(), source_sha256=c.source.checksum, revision=1)
