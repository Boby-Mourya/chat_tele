from __future__ import annotations

import asyncio
import hashlib
import io
import json
import math
import re
import tempfile
import zipfile
from pathlib import Path
from uuid import UUID

import fitz  # type: ignore[import-untyped]
import structlog
from docx import Document
from pypdf import PdfReader
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.config import get_settings
from northstar_api.models import (
    Agent,
    DocumentChunk,
    IngestionJob,
    JobStatus,
    KnowledgeKind,
    KnowledgeSnapshot,
    KnowledgeSource,
    KnowledgeStatus,
)
from northstar_api.modules.knowledge.web_sources import (
    CrawlIncomplete,
    SitemapMaterialization,
    materialize_sitemap,
)
from northstar_api.services.hybrid_extraction import (
    ExtractionPackage,
    PageCheckpoint,
    configuration,
    decode_page_checkpoint,
    encode_page_checkpoint,
    extract_document,
)
from northstar_api.services.object_store import object_store
from northstar_api.services.outbox import enqueue_event
from northstar_api.services.safe_fetch import fetch_public_text
from northstar_api.services.vision import extract_vision_text

logger = structlog.get_logger(__name__)


class ExtractionYield(Exception):
    """A durable page batch completed; resume in a fresh worker delivery."""


def validate_embedding_batch(
    vectors: list[list[float]], expected_count: int, dimension: int
) -> None:
    """Validate a provider embedding response for legacy callers.

    Knowledge publication currently uses the vectorless lexical index, but this
    helper remains part of the ingestion compatibility surface for deployments
    and integrations that still validate an embedding response before choosing
    their own index backend.
    """
    if len(vectors) != expected_count:
        raise ValueError(f"Embedding count mismatch: expected {expected_count}, got {len(vectors)}")
    for index, vector in enumerate(vectors):
        if len(vector) != dimension:
            raise ValueError(
                f"Embedding dimension mismatch at chunk {index}: expected {dimension}, got {len(vector)}"
            )
        if not all(math.isfinite(value) for value in vector):
            raise ValueError(f"Embedding contains a non-finite value at chunk {index}")
        if not any(value != 0 for value in vector):
            raise ValueError(f"Embedding is a zero vector at chunk {index}")


def semantic_chunks(text: str, target_words: int = 220, overlap_words: int = 35) -> list[str]:
    """Create chunks without crossing PDF page boundaries."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []

    # PDF pages are separated by explicit markers inserted during extraction.
    pages = re.split(r"\n\s*===PDF_PAGE:\d+===\s*\n", normalized)

    chunks: list[str] = []

    for page in pages:
        page = page.strip()
        if not page:
            continue

        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", page) if part.strip()]
        if not paragraphs:
            continue

        current: list[str] = []
        current_words = 0

        for paragraph in paragraphs:
            paragraph_words = paragraph.split()

            # Very long paragraphs are split independently.
            if len(paragraph_words) > target_words * 2:
                if current:
                    chunks.append(" ".join(current).strip())
                    current = []
                    current_words = 0

                step = max(1, target_words - overlap_words)
                for start in range(0, len(paragraph_words), step):
                    part = paragraph_words[start : start + target_words]
                    if part:
                        chunks.append(" ".join(part).strip())
                continue

            if current and current_words + len(paragraph_words) > target_words:
                chunks.append(" ".join(current).strip())

                overlap = current[-overlap_words:] if overlap_words else []
                current = overlap + paragraph_words
                current_words = len(current)
            else:
                current.extend(paragraph_words)
                current_words += len(paragraph_words)

        if current:
            chunks.append(" ".join(current).strip())

    return [chunk for chunk in chunks if chunk]


def extraction_page_text(page: dict[str, object]) -> str:
    """Use the review text when available, otherwise retain extracted page text."""
    for field in ("selected_text", "native_text", "visual_text"):
        value = page.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def approved_extraction_chunks(record: dict) -> list[tuple[str, dict[str, object]]]:
    """Project approved physical regions into searchable chunks with provenance."""
    result: list[tuple[str, dict[str, object]]] = []
    heading_stack: list[tuple[int | None, str, str]] = []
    for page in record.get("pages", []):
        blocks = [item for item in page.get("blocks", []) if item.get("status") != "split"]
        # Native-only pages have no visual regions, but retain page citations
        # and quality provenance in the same vectorless chunk store.
        if not blocks:
            page_text = extraction_page_text(page)
            page_parts = semantic_chunks(page_text)
            for part_index, part in enumerate(page_parts):
                result.append(
                    (
                        part,
                        {
                            "chunk_type": "text",
                            "page_number": page.get("number"),
                            "printed_page_label": page.get("printed_page_label"),
                            "part_index": part_index,
                            "part_count": len(page_parts),
                            "extraction_revision": record.get("extraction_revision"),
                            "page_quality": page.get("quality"),
                            "canonical_chunk_id": hashlib.sha256(
                                f"{record.get('source_sha256')}:{record.get('extraction_revision')}:page:{page.get('number')}:{part_index}:{part}".encode()
                            ).hexdigest(),
                        },
                    )
                )
            continue
        for block_ordinal, block in enumerate(blocks):
            text = str(block.get("selected_text") or "").strip()
            if not text:
                continue
            block_type = str(block.get("type", "unknown"))
            if block_type == "heading":
                raw_level = block.get("heading_level", block.get("headingLevel", block.get("level")))
                try:
                    heading_level = int(raw_level) if raw_level is not None else None
                except (TypeError, ValueError):
                    heading_level = None
                if heading_level is not None and not 1 <= heading_level <= 9:
                    heading_level = None
                heading_id = str(block.get("id") or hashlib.sha256(text.encode("utf-8")).hexdigest())
                if heading_level is None:
                    # Unknown hierarchy is retained instead of pretending it is a
                    # known peer. Keep it below the current known ancestry.
                    heading_stack.append((None, heading_id, text[:240]))
                else:
                    while heading_stack and (
                        heading_stack[-1][0] is None or heading_stack[-1][0] >= heading_level
                    ):
                        heading_stack.pop()
                    heading_stack.append((heading_level, heading_id, text[:240]))
            section_path = [heading[2] for heading in heading_stack]
            section_ids = [heading[1] for heading in heading_stack]
            section_levels = [heading[0] for heading in heading_stack]
            if block_type in {"table", "equation", "question", "answer_key", "figure", "caption"}:
                parts = [text] if len(text.split()) <= 440 else semantic_chunks(text, target_words=220, overlap_words=50)
            else:
                parts = semantic_chunks(text)
            block_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            for part_index, part in enumerate(parts):
                result.append(
                    (
                        part,
                        {
                            "chunk_type": block_type,
                            "block_ordinal": block_ordinal,
                            "block_text_hash": block_hash,
                            "part_count": len(parts),
                            "section_path": list(section_path),
                            "section_ids": list(section_ids),
                            "section_levels": list(section_levels),
                            "heading_level": heading_stack[-1][0] if block_type == "heading" else None,
                            "page_number": page.get("number"),
                            "printed_page_label": page.get("printed_page_label"),
                            "block_id": block.get("id"),
                            "bbox_px": block.get("bbox_px"),
                            "source_artifact": block.get("crop"),
                            "part_index": part_index,
                            "extraction_revision": record.get("extraction_revision"),
                            "page_quality": page.get("quality"),
                            "canonical_chunk_id": hashlib.sha256(
                                f"{record.get('source_sha256')}:{record.get('extraction_revision')}:{block.get('id')}:{part_index}:{part}".encode()
                            ).hexdigest(),
                        },
                    )
                )
    return result


async def ingest_source_async(session: AsyncSession, source_id: UUID) -> None:
    source = await session.scalar(select(KnowledgeSource).where(KnowledgeSource.id == source_id))
    if not source:
        return
    job = await session.scalar(
        select(IngestionJob)
        .where(IngestionJob.source_id == source.id)
        .order_by(IngestionJob.created_at.desc())
    )
    if job:
        if job.status == JobStatus.SUCCEEDED:
            return
        job.status = JobStatus.RUNNING
        job.step = "chunking"
        job.progress = 20
        job.attempts += 1
    source.status = KnowledgeStatus.PROCESSING
    source.error = None
    await session.commit()
    web_crawl: SitemapMaterialization | None = None
    try:
        if source.kind == KnowledgeKind.FILE and source.object_key and source.content is None:
            data, metadata = await object_store.download(source.object_key)
            if source.checksum and hashlib.sha256(data).hexdigest() != source.checksum:
                raise ValueError("Uploaded source checksum does not match the preserved original")
            if job:
                job.step = "extracting"
                job.progress = 30
                await session.commit()
            settings = get_settings()
            version = source.revision or 1
            source_hash = hashlib.sha256(data).hexdigest()
            vision_identity = hashlib.sha256(
                json.dumps(configuration(settings), sort_keys=True).encode()
            ).hexdigest()
            raw_pages = await object_store.load_extraction_pages(source.tenant_id, source.id, version=version)
            resume_pages: dict[int, PageCheckpoint] = {}
            for number in sorted(raw_pages):
                if number != len(resume_pages) + 1:
                    raise ValueError("Extraction checkpoints are not a contiguous page prefix")
                resume_pages[number] = decode_page_checkpoint(
                    raw_pages[number],
                    source_sha256=source_hash,
                    model=vision_identity,
                    version=version,
                    page_number=number,
                )

            async def checkpoint(page: dict, image: bytes, page_issues: list[dict]) -> None:
                number = int(page["number"])
                if number in resume_pages:
                    return
                encoded = encode_page_checkpoint(
                    page,
                    image,
                    page_issues,
                    source_sha256=source_hash,
                    model=vision_identity,
                    version=version,
                )
                await object_store.put_extraction_page(
                    source.tenant_id,
                    source.id,
                    version=version,
                    page_number=number,
                    data=encoded,
                )
                if job:
                    job.step = f"extracted_page_{number}"
                    job.progress = min(90, 30 + number)
                    await session.commit()
                if (
                    settings.background_dispatch_enabled
                    and number - len(resume_pages) >= settings.extraction_pages_per_task
                ):
                    raise ExtractionYield()

            suffixes = {
                "application/pdf": "pdf",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
                "text/plain": "txt",
                "text/markdown": "md",
                "image/png": "png",
                "image/jpeg": "jpg",
                "image/tiff": "tiff",
            }
            suffix = suffixes.get(
                str(metadata.get("content_type", "")).lower(), source.object_key.rsplit(".", 1)[-1]
            )
            filename = (
                source.name if source.name.lower().endswith("." + suffix) else source.name + "." + suffix
            )
            package = await extract_document(
                data, filename, settings, resume_pages=resume_pages, on_page=checkpoint
            )
            package.record["source_display_name"] = source.name
            package.record["extraction_revision"] = source.revision or 1
            source.extraction_key = await object_store.put_extraction(
                source.tenant_id, source.id, package.archive(), version=source.revision or 1
            )
            # Low-confidence pages are preserved but must be approved before they
            # enter the vectorless index. High-confidence native text can proceed
            # without an unnecessary vision call or human review.
            if package.record["review_status"] != "verified_release":
                source.status = KnowledgeStatus.NEEDS_REVIEW
                source.extraction_issue_count = sum(
                    issue.get("status") != "resolved" for issue in package.issues
                )
                source.size_label = f"{len(package.record['pages'])} source units"
                source.chunk_count = 0
                if job:
                    job.status = JobStatus.SUCCEEDED
                    job.step = "review_required"
                    job.progress = 100
                await session.commit()
                return
            approved = package
            content = "\n\n".join(
                f"===PDF_PAGE:{page['number']}===\n{extraction_page_text(page)}"
                if page.get("source_unit") == "pdf_page" else extraction_page_text(page)
                for page in package.record["pages"]
                if extraction_page_text(page)
            )
            source.content = content
            source.size_label = f"{len(package.record['pages'])} source units"
        if source.kind == KnowledgeKind.FILE:
            if not source.extraction_key or not source.extraction_key.startswith(
                f"extractions/{source.tenant_id}/{source.id}/"
            ):
                raise ValueError("File has no reviewed extraction evidence")
            evidence, _ = await object_store.download(source.extraction_key, limit_bytes=1024**3)
            approved = ExtractionPackage.from_archive(
                evidence, source_sha256=source.checksum, revision=source.revision
            )
            content = "\n\n".join(
                f"===PDF_PAGE:{p['number']}===\n{extraction_page_text(p)}"
                if p.get("source_unit") == "pdf_page" else extraction_page_text(p)
                for p in approved.record["pages"]
                if extraction_page_text(p)
            )
            if source.content != content:
                raise ValueError("Indexing text differs from verified source records")
        elif source.kind == KnowledgeKind.SITEMAP and source.url and not source.content:
            web_crawl = await _materialize_sitemap_result(source)
            content = web_crawl.text
        else:
            content = await _materialize_text(source)
        if not content and source.kind != KnowledgeKind.FILE:
            raise ValueError("Source has no extracted text")
        settings = get_settings()
        if len(content) > settings.knowledge_max_extracted_characters:
            raise ValueError("Source text exceeds the configured extraction limit")
        structured_chunks = approved_extraction_chunks(approved.record) if source.kind == KnowledgeKind.FILE else []
        chunks_with_metadata = structured_chunks or [
            (chunk, {"chunk_type": "text"}) for chunk in semantic_chunks(content)
        ]
        if web_crawl is not None:
            # Never blend separate source pages into a single chunk. Query-driven
            # page identity and the acquired text hash survive indexing.
            chunks_with_metadata = [
                (
                    chunk,
                    {
                        "chunk_type": "web_page",
                        "source_url": page.final_url,
                        "requested_url": page.requested_url,
                        "fetched_at": page.fetched_at,
                        "page_text_sha256": page.manifest_entry()["text_sha256"],
                        "representation": "guarded-visible-text",
                    },
                )
                for page in web_crawl.pages
                for chunk in semantic_chunks(page.text)
            ]
        chunks = [chunk for chunk, _ in chunks_with_metadata]
        if not chunks:
            raise ValueError("Source produced no usable chunks")
        if len(chunks) > settings.knowledge_max_chunks:
            raise ValueError("Source produced more chunks than the configured limit")
        if job:
            job.step = "indexing"
            job.progress = 55
            await session.commit()
        agent = await session.scalar(
            select(Agent).where(Agent.id == source.agent_id).with_for_update()
        )
        if not agent:
            raise ValueError("Knowledge source agent no longer exists")
        publication_revision = agent.published_knowledge_revision + 1
        agent.published_knowledge_revision = publication_revision
        await session.execute(delete(DocumentChunk).where(DocumentChunk.source_id == source.id))
        for ordinal, content_chunk in enumerate(chunks):
            chunk_metadata = dict(chunks_with_metadata[ordinal][1])
            chunk_metadata["content_hash"] = hashlib.sha256(content_chunk.encode("utf-8")).hexdigest()
            session.add(
                DocumentChunk(
                    tenant_id=source.tenant_id,
                    workspace_id=source.workspace_id,
                    agent_id=source.agent_id,
                    source_id=source.id,
                    ordinal=ordinal,
                    content=content_chunk,
                    token_count=max(1, round(len(content_chunk.split()) * 1.35)),
                    approved=True,
                    revision=publication_revision,
                    # Vectorless RAG deliberately persists searchable text and
                    # provenance only; no embedding is generated or stored.
                    embedding_model=None,
                    embedding=None,
                    metadata_json=chunk_metadata,
                )
            )
        source.status = KnowledgeStatus.READY
        source.chunk_count = len(chunks)
        source.size_label = f"{len(content.split()):,} words"
        await session.flush()
        published_sources = (
            await session.scalars(
                select(KnowledgeSource)
                .where(
                    KnowledgeSource.tenant_id == source.tenant_id,
                    KnowledgeSource.agent_id == source.agent_id,
                    KnowledgeSource.status == KnowledgeStatus.READY,
                )
                .order_by(KnowledgeSource.id)
            )
        ).all()
        session.add(
            KnowledgeSnapshot(
                tenant_id=source.tenant_id,
                workspace_id=source.workspace_id,
                agent_id=source.agent_id,
                revision=publication_revision,
                manifest={
                    "version": 1,
                    "retrievalMode": "lexical",
                    "ingestedSourceCrawl": web_crawl.manifest if web_crawl is not None else None,
                    "sources": [
                        {
                            "sourceId": str(item.id),
                            "sourceRevision": item.revision,
                            "checksum": item.checksum,
                            "chunkCount": item.chunk_count,
                        }
                        for item in published_sources
                    ],
                },
            )
        )
        if job:
            job.status = JobStatus.SUCCEEDED
            job.step = "complete"
            job.progress = 100
        enqueue_event(
            session,
            tenant_id=source.tenant_id,
            aggregate_type="knowledge_source",
            aggregate_id=source.id,
            event_type="knowledge.source.ingested.v1",
            payload={"sourceId": str(source.id), "agentId": str(source.agent_id), "chunks": len(chunks)},
        )
        await session.commit()
    except ExtractionYield:
        if job:
            job.status = JobStatus.QUEUED
            job.step = "extraction_checkpointed"
        await session.commit()
        raise
    except Exception as exc:
        # Discard staged chunks, revision changes, and pointer updates before
        # persisting failure state in a clean transaction.
        rollback = getattr(session, "rollback", None)
        if rollback is None:  # Minimal unit-test session doubles have no transaction API.
            failed_source, failed_job = source, job
        else:
            await rollback()
            failed_source = await session.scalar(
                select(KnowledgeSource).where(KnowledgeSource.id == source_id)
            )
            failed_job = await session.scalar(
                select(IngestionJob)
                .where(IngestionJob.source_id == source_id)
                .order_by(IngestionJob.created_at.desc())
            )
        if failed_source:
            failed_source.status = KnowledgeStatus.FAILED
            failed_source.error = (
                str(exc)[:1000] if isinstance(exc, CrawlIncomplete)
                else "Ingestion failed; inspect the job log."
            )
        if failed_job:
            failed_job.status = JobStatus.FAILED
            failed_job.step = "failed"
            failed_job.error_json = {"type": type(exc).__name__, "message": str(exc)[:400]}
            if isinstance(exc, CrawlIncomplete):
                failed_job.error_json = {**failed_job.error_json, "crawl_manifest": exc.manifest}
        await session.commit()
        raise


async def _materialize_text(source: KnowledgeSource) -> str:
    if source.content:
        return source.content.strip()
    if source.url:
        if source.kind == KnowledgeKind.SITEMAP:
            return await _materialize_sitemap(source)

        if source.kind == KnowledgeKind.URL:
            return await _materialize_webpage_with_vision(source)

        text, final_url = await fetch_public_text(source.url)
        source.url = final_url
        return text.strip()
    if source.object_key:
        data, metadata = await object_store.download(source.object_key)
        content_type = str(metadata.get("content_type") or "").lower()
        if content_type == "application/pdf" or source.name.lower().endswith(".pdf"):
            reader = PdfReader(io.BytesIO(data))
            settings = get_settings()

            if len(reader.pages) > settings.knowledge_max_pdf_pages:
                raise ValueError("PDF exceeds the configured page limit")

            pages: list[str] = []

            # PDF extraction:
            # Use normal PDF text first.
            # Use Vision when the page has embedded images
            # or when normal PDF text is missing.
            extracted_characters = 0

            with tempfile.TemporaryDirectory() as temp_dir:
                pdf = fitz.open(stream=data, filetype="pdf")

                for page_number, page in enumerate(reader.pages):
                    # 1. Extract normal/selectable PDF text.
                    text = page.extract_text() or ""
                    text = text.strip()

                    extracted_characters += len(text)

                    if extracted_characters > settings.knowledge_max_extracted_characters:
                        raise ValueError("PDF text exceeds the configured extraction limit")

                    # 2. Check whether this page contains embedded images.
                    fitz_page = pdf[page_number]
                    has_images = bool(fitz_page.get_images(full=True))

                    # 3. If text is available and there are no images,
                    #    use the normal PDF text only.
                    if text and not has_images:
                        pages.append(text)
                        continue

                    # 4. Otherwise, render the page and use Vision.
                    pixmap = fitz_page.get_pixmap(
                        matrix=fitz.Matrix(2, 2),
                        alpha=False,
                    )

                    image_path = Path(temp_dir) / f"vision_page_{page_number + 1:03d}.png"

                    pixmap.save(str(image_path))

                    vision_text = await asyncio.to_thread(
                        extract_vision_text,
                        str(image_path),
                    )

                    visual_content = vision_text.strip()

                    # 5. Build ONE clean result for this page.
                    page_parts: list[str] = []

                    if text:
                        page_parts.append(text)

                    if visual_content:
                        page_parts.append(
                            f"VISUAL CONTENT FROM PDF PAGE {page_number + 1}:\n{visual_content}"
                        )

                    if page_parts:
                        page_content = "\n\n".join(page_parts)

                        extracted_characters += len(page_content)

                        if extracted_characters > settings.knowledge_max_extracted_characters:
                            raise ValueError("PDF text exceeds the configured extraction limit")

                        pages.append(page_content)

                pdf.close()

            return "\n\n".join(
                f"===PDF_PAGE:{index}===\n{page}" for index, page in enumerate(pages, start=1)
            ).strip()
        if "wordprocessingml.document" in content_type or source.name.lower().endswith(".docx"):
            settings = get_settings()

            try:
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    members = archive.infolist()
                    expanded_size = sum(member.file_size for member in members)

                    if len(members) > 5_000:
                        raise ValueError("DOCX contains too many archive members")

                    if expanded_size > settings.knowledge_max_docx_uncompressed_bytes:
                        raise ValueError("DOCX exceeds the configured expanded-size limit")

            except zipfile.BadZipFile as exc:
                raise ValueError("DOCX archive is invalid") from exc

            document = Document(io.BytesIO(data))

            sections: list[str] = []

            # Existing paragraph extraction
            paragraphs = [
                paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()
            ]

            if paragraphs:
                sections.append("\n\n".join(paragraphs))

            # Existing document tables + structured table text
            tables: list[str] = []

            for table in document.tables:
                rows: list[str] = []

                for row in table.rows:
                    cells = [cell.text.strip() for cell in row.cells]

                    if any(cells):
                        rows.append(" | ".join(cells))

                if rows:
                    tables.append("\n".join(rows))

            if tables:
                sections.append("TABLE CONTENT FROM DOCX:\n\n" + "\n\n".join(tables))

            # NEXORA Vision extraction for embedded images
            try:
                with tempfile.TemporaryDirectory() as temp_dir:
                    with zipfile.ZipFile(io.BytesIO(data)) as archive:
                        image_members = [
                            member
                            for member in archive.infolist()
                            if member.filename.startswith("word/media/")
                        ]

                        for image_number, member in enumerate(
                            image_members,
                            start=1,
                        ):
                            suffix = Path(member.filename).suffix or ".png"

                            image_path = Path(temp_dir) / f"docx_image_{image_number:03d}{suffix}"

                            with archive.open(member) as source_file:
                                image_path.write_bytes(source_file.read())

                            vision_text = await asyncio.to_thread(
                                extract_vision_text,
                                str(image_path),
                            )

                            if vision_text.strip():
                                sections.append(
                                    f"VISUAL CONTENT FROM DOCX IMAGE {image_number}:\n{vision_text.strip()}"
                                )

            except Exception as exc:
                logger.warning(
                    "docx_vision_extraction_failed",
                    source_id=str(source.id),
                    error=type(exc).__name__,
                )

            return "\n\n".join(sections).strip()
        if content_type.startswith("text/") or source.name.lower().endswith((".txt", ".md")):
            return data.decode("utf-8", errors="replace").strip()
        raise ValueError("Uploaded file type is not supported")
    return ""


async def _materialize_webpage_with_vision(source: KnowledgeSource) -> str:
    """Fetch one web source through the pinned-IP, redirect-checked transport.

    The legacy requests/Playwright crawler bypassed that transport for later
    pages and browser subresources. Multi-page/browser ingestion stays disabled
    until it runs in a network-isolated worker with controlled egress.
    """
    assert source.url is not None

    initial_text, final_url = await fetch_public_text(source.url)
    source.url = final_url
    return f"Source page: {final_url}\n\n{initial_text.strip()}".strip()


async def _materialize_sitemap_result(source: KnowledgeSource) -> SitemapMaterialization:
    assert source.url is not None
    settings = get_settings()
    result = await materialize_sitemap(
        source.url,
        max_urls=settings.knowledge_sitemap_max_urls,
        max_characters=settings.knowledge_max_extracted_characters,
    )
    source.url = result.sitemap_url
    return result


async def _materialize_sitemap(source: KnowledgeSource) -> str:
    """Compatibility entrypoint; incomplete crawls are never returned as usable text."""
    return (await _materialize_sitemap_result(source)).text
