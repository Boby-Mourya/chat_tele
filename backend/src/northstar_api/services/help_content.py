from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
import yaml
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.config import get_settings
from northstar_api.help_models import HelpArticle, HelpArticleChunk, HelpArticleStatus, HelpCategory
from northstar_api.models import Role
from northstar_api.services.llm import ModelUnavailableError, nvidia_adapter

logger = structlog.get_logger(__name__)

HELP_CONTENT_ROOT = Path(__file__).resolve().parents[3] / "help_content"
_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.DOTALL)
_HEADING = re.compile(r"^#{1,4}\s+(.+?)\s*$")
_WORD = re.compile(r"[\w'-]+", re.UNICODE)


@dataclass(slots=True)
class ArticleDocument:
    slug: str
    title: str
    summary: str
    category: str
    roles: list[str]
    keywords: list[str]
    featured: bool
    sort_order: int
    body: str
    content_hash: str
    reading_minutes: int


def _require_str(meta: dict[str, Any], key: str, *, max_length: int) -> str:
    value = str(meta.get(key, "")).strip()
    if not value:
        raise ValueError(f"missing required front matter field: {key}")
    if len(value) > max_length:
        raise ValueError(f"front matter field {key} exceeds {max_length} characters")
    return value


def _parse_article(path: Path) -> ArticleDocument:
    raw = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    match = _FRONT_MATTER.match(raw)
    if not match:
        raise ValueError("article must start with YAML front matter")
    meta = yaml.safe_load(match.group(1)) or {}
    if not isinstance(meta, dict):
        raise ValueError("article front matter must be a mapping")
    body = match.group(2).strip()
    if not body:
        raise ValueError("article body cannot be empty")

    slug = _require_str(meta, "slug", max_length=160)
    title = _require_str(meta, "title", max_length=240)
    summary = _require_str(meta, "summary", max_length=1000)
    category = _require_str(meta, "category", max_length=100)
    roles = [str(value).strip().lower() for value in (meta.get("roles") or [])]
    allowed_roles = {item.value for item in Role}
    if not roles or any(role not in allowed_roles for role in roles):
        raise ValueError(f"roles must be one or more of {sorted(allowed_roles)}")
    keywords = [str(value).strip()[:80] for value in (meta.get("keywords") or []) if str(value).strip()]
    featured = bool(meta.get("featured", False))
    sort_order = int(meta.get("sort_order", 0))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    reading_minutes = max(1, math.ceil(len(_WORD.findall(body)) / 220))
    return ArticleDocument(
        slug=slug,
        title=title,
        summary=summary,
        category=category,
        roles=roles,
        keywords=keywords,
        featured=featured,
        sort_order=sort_order,
        body=body,
        content_hash=digest,
        reading_minutes=reading_minutes,
    )


def _chunk_markdown(body: str, *, target_words: int = 180, max_words: int = 280) -> list[tuple[str, str]]:
    chunks: list[tuple[str, str]] = []
    headings: list[str] = []
    current: list[str] = []
    current_words = 0

    def flush() -> None:
        nonlocal current, current_words
        text = "\n".join(current).strip()
        if text:
            chunks.append((" > ".join(headings[-3:]), text))
        current = []
        current_words = 0

    for line in body.splitlines():
        heading_match = _HEADING.match(line)
        if heading_match:
            if current_words >= target_words:
                flush()
            level = len(line) - len(line.lstrip("#"))
            title = heading_match.group(1).strip()
            headings[:] = headings[: max(0, level - 1)]
            headings.append(title)
        words = len(_WORD.findall(line))
        if current and current_words + words > max_words:
            flush()
        current.append(line)
        current_words += words
    flush()
    return chunks or [("", body.strip())]


async def _embed_chunks(chunks: list[tuple[str, str]]) -> tuple[list[list[float] | None], str | None]:
    texts = [text for _, text in chunks]
    try:
        vectors = await nvidia_adapter.embed_documents(texts)
        return vectors, get_settings().nvidia_embedding_model
    except ModelUnavailableError:
        logger.warning("help_content_embedding_unavailable", chunk_count=len(chunks))
        return [None for _ in chunks], None


async def sync_help_content(
    session: AsyncSession,
    *,
    root: Path | None = None,
) -> None:
    # Multiple API replicas can start together. Serialize the global docs sync on PostgreSQL
    # so unique slugs and chunk rebuilds remain deterministic without creating a new service.
    if session.bind and session.bind.dialect.name == "postgresql":
        await session.execute(text("SELECT pg_advisory_xact_lock(741932581204)"))
    content_root = root or HELP_CONTENT_ROOT
    categories_path = content_root / "categories.yml"
    if not categories_path.exists():
        logger.warning("help_content_categories_missing", path=str(categories_path))
        return

    raw_categories = yaml.safe_load(categories_path.read_text(encoding="utf-8")) or []
    if not isinstance(raw_categories, list):
        raise ValueError("help_content/categories.yml must contain a list")

    category_rows: dict[str, HelpCategory] = {}
    for item in raw_categories:
        if not isinstance(item, dict):
            raise ValueError("each Help category must be a mapping")
        slug = str(item.get("slug", "")).strip()
        title = str(item.get("title", "")).strip()
        if not slug or not title:
            raise ValueError("Help category slug and title are required")
        row = await session.scalar(select(HelpCategory).where(HelpCategory.slug == slug))
        if row is None:
            row = HelpCategory(slug=slug, title=title)
            session.add(row)
        row.title = title[:160]
        row.description = str(item.get("description", "")).strip()[:500]
        row.icon = str(item.get("icon", "CircleHelp")).strip()[:80] or "CircleHelp"
        row.sort_order = int(item.get("sort_order", 0))
        row.is_active = bool(item.get("is_active", True))
        category_rows[slug] = row
    await session.flush()

    documents: list[ArticleDocument] = []
    for path in sorted(content_root.glob("**/*.md")):
        try:
            document = _parse_article(path)
            if document.category not in category_rows:
                raise ValueError(f"unknown category: {document.category}")
            documents.append(document)
        except Exception as exc:
            logger.error("help_content_article_invalid", path=str(path), error=str(exc))
            raise

    active_slugs = {document.slug for document in documents}
    existing_rows = (await session.scalars(select(HelpArticle))).all()
    for article in existing_rows:
        if article.slug not in active_slugs and article.status != HelpArticleStatus.ARCHIVED:
            article.status = HelpArticleStatus.ARCHIVED

    changed = 0
    for document in documents:
        article = await session.scalar(select(HelpArticle).where(HelpArticle.slug == document.slug))
        is_new = article is None
        if article is None:
            article = HelpArticle(
                category_id=category_rows[document.category].id,
                slug=document.slug,
                title=document.title,
                summary=document.summary,
                body_markdown=document.body,
                keywords_json=document.keywords,
                audience_roles_json=document.roles,
                featured=document.featured,
                status=HelpArticleStatus.PUBLISHED,
                sort_order=document.sort_order,
                reading_minutes=document.reading_minutes,
                content_hash=document.content_hash,
                published_at=datetime.now(UTC),
            )
            session.add(article)
            await session.flush()
        content_changed = is_new or article.content_hash != document.content_hash
        article.category_id = category_rows[document.category].id
        article.title = document.title
        article.summary = document.summary
        article.body_markdown = document.body
        article.keywords_json = document.keywords
        article.audience_roles_json = document.roles
        article.featured = document.featured
        article.status = HelpArticleStatus.PUBLISHED
        article.sort_order = document.sort_order
        article.reading_minutes = document.reading_minutes
        article.content_hash = document.content_hash
        if article.published_at is None:
            article.published_at = datetime.now(UTC)

        if content_changed:
            chunks = _chunk_markdown(document.body)
            vectors, embedding_model = await _embed_chunks(chunks)
            await session.execute(delete(HelpArticleChunk).where(HelpArticleChunk.article_id == article.id))
            for index, ((heading, chunk_text), vector) in enumerate(zip(chunks, vectors, strict=True)):
                session.add(
                    HelpArticleChunk(
                        article_id=article.id,
                        chunk_index=index,
                        heading_path=heading[:500],
                        content=chunk_text,
                        embedding_model=embedding_model,
                        embedding=vector,
                    )
                )
            changed += 1

    await session.commit()
    logger.info(
        "help_content_synced",
        categories=len(category_rows),
        articles=len(documents),
        reindexed=changed,
    )
