from __future__ import annotations

from uuid import uuid4

import pytest

from northstar_api.models import KnowledgeKind, KnowledgeSource
from northstar_api.modules.knowledge import web_sources
from northstar_api.services import ingestion


def test_approved_chunks_preserve_heading_ancestry_by_level() -> None:
    record = {
        "source_sha256": "source",
        "extraction_revision": 3,
        "pages": [{
            "number": 1,
            "blocks": [
                {"id": "h1", "type": "heading", "heading_level": 1, "selected_text": "Chapter"},
                {"id": "h2", "type": "heading", "heading_level": 2, "selected_text": "Section"},
                {"id": "h3", "type": "heading", "heading_level": 3, "selected_text": "Topic"},
                {"id": "p1", "type": "paragraph", "selected_text": "Nested answer."},
                {"id": "h2b", "type": "heading", "heading_level": 2, "selected_text": "Next section"},
                {"id": "p2", "type": "paragraph", "selected_text": "Sibling answer."},
            ],
        }],
    }

    chunks = ingestion.approved_extraction_chunks(record)
    nested = next(metadata for text, metadata in chunks if text == "Nested answer.")
    sibling = next(metadata for text, metadata in chunks if text == "Sibling answer.")

    assert nested["section_path"] == ["Chapter", "Section", "Topic"]
    assert nested["section_ids"] == ["h1", "h2", "h3"]
    assert nested["section_levels"] == [1, 2, 3]
    assert sibling["section_path"] == ["Chapter", "Next section"]
    assert sibling["section_ids"] == ["h1", "h2b"]


def test_approved_chunks_retain_unknown_heading_level_for_review() -> None:
    chunks = ingestion.approved_extraction_chunks({
        "source_sha256": "source",
        "extraction_revision": 1,
        "pages": [{"number": 1, "blocks": [
            {"id": "known", "type": "heading", "heading_level": 1, "selected_text": "Known"},
            {"id": "unknown", "type": "heading", "selected_text": "Unclassified"},
            {"id": "body", "type": "paragraph", "selected_text": "Body"},
        ]}],
    })

    body = next(metadata for text, metadata in chunks if text == "Body")
    unknown = next(metadata for text, metadata in chunks if text == "Unclassified")
    assert body["section_path"] == ["Known", "Unclassified"]
    assert body["section_ids"] == ["known", "unknown"]
    assert unknown["heading_level"] is None


async def test_sitemap_ingestion_rejects_incomplete_out_of_scope_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetched: list[str] = []

    async def fetch(url: str, **_: int) -> tuple[str, str]:
        fetched.append(url)
        if url.endswith("sitemap.xml"):
            return (
                "<urlset><url><loc>https://docs.example/returns</loc></url>"
                "<url><loc>https://attacker.example/private</loc></url></urlset>",
                "https://docs.example/sitemap.xml",
            )
        return "Returns are accepted within 30 days.", url

    monkeypatch.setattr(web_sources, "fetch_public_text", fetch)
    source = KnowledgeSource(
        tenant_id=uuid4(),
        agent_id=uuid4(),
        name="Documentation sitemap",
        kind=KnowledgeKind.SITEMAP,
        url="https://docs.example/sitemap.xml",
    )

    with pytest.raises(web_sources.CrawlIncomplete):
        await ingestion._materialize_text(source)

    # Reject the manifest before any page fetch rather than silently claiming
    # that the in-scope subset is a complete crawl.
    assert fetched == ["https://docs.example/sitemap.xml"]


async def test_url_ingestion_uses_only_guarded_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    fetched: list[str] = []

    async def fetch(url: str, **_: int) -> tuple[str, str]:
        fetched.append(url)
        return "Approved support policy.", "https://docs.example/policy"

    monkeypatch.setattr(ingestion, "fetch_public_text", fetch)
    source = KnowledgeSource(
        tenant_id=uuid4(),
        agent_id=uuid4(),
        name="Support policy",
        kind=KnowledgeKind.URL,
        url="https://docs.example/policy?version=2",
    )

    content = await ingestion._materialize_text(source)

    assert fetched == ["https://docs.example/policy?version=2"]
    assert source.url == "https://docs.example/policy"
    assert content == "Source page: https://docs.example/policy\n\nApproved support policy."
