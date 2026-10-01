from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.help_config import HelpSettings, get_help_settings
from northstar_api.help_models import HelpArticle, HelpArticleChunk, HelpArticleStatus, HelpCategory
from northstar_api.models import Role
from northstar_api.services.llm import ModelUnavailableError, nvidia_adapter

_WORD = re.compile(r"[\w'-]+", re.UNICODE)


@dataclass(slots=True)
class HelpSearchHit:
    article: HelpArticle
    category: HelpCategory
    score: float
    snippet: str


@dataclass(slots=True)
class HelpEvidence:
    article: HelpArticle
    category: HelpCategory
    chunk: HelpArticleChunk
    score: float


def _visible(role: Role):
    # JSON role filtering is applied portably after selecting published candidates.
    return role.value


def _tokens(value: str) -> set[str]:
    return {token for token in _WORD.findall(value.casefold()) if len(token) > 1}


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norm_left = math.sqrt(sum(value * value for value in left))
    norm_right = math.sqrt(sum(value * value for value in right))
    return dot / (norm_left * norm_right) if norm_left and norm_right else 0.0


def _snippet(text: str, query_tokens: set[str], *, limit: int = 260) -> str:
    clean = re.sub(r"[#*_`>\[\]()]+", " ", text)
    clean = re.sub(r"\s+", " ", clean).strip()
    if not clean:
        return ""
    lower = clean.casefold()
    positions = [lower.find(token) for token in query_tokens if lower.find(token) >= 0]
    start = max(0, (min(positions) if positions else 0) - 70)
    end = min(len(clean), start + limit)
    prefix = "…" if start else ""
    suffix = "…" if end < len(clean) else ""
    return f"{prefix}{clean[start:end].strip()}{suffix}"


class HelpSearchService:
    def __init__(self, settings: HelpSettings | None = None) -> None:
        self.settings = settings or get_help_settings()

    async def _articles(self, session: AsyncSession, role: Role, category: str | None = None) -> list[tuple[HelpArticle, HelpCategory]]:
        statement = (
            select(HelpArticle, HelpCategory)
            .join(HelpCategory, HelpCategory.id == HelpArticle.category_id)
            .where(HelpArticle.status == HelpArticleStatus.PUBLISHED, HelpCategory.is_active.is_(True))
            .order_by(HelpCategory.sort_order, HelpArticle.sort_order, HelpArticle.title)
        )
        if category:
            statement = statement.where(HelpCategory.slug == category)
        rows = (await session.execute(statement)).all()
        role_value = _visible(role)
        return [(article, cat) for article, cat in rows if role_value in (article.audience_roles_json or [])]

    async def search(
        self,
        session: AsyncSession,
        *,
        role: Role,
        query: str,
        category: str | None = None,
        limit: int | None = None,
    ) -> list[HelpSearchHit]:
        normalized = query.strip()
        query_tokens = _tokens(normalized)
        if not query_tokens:
            return []
        candidate_limit = min(limit or self.settings.help_search_candidate_limit, self.settings.help_search_candidate_limit)
        visible_rows = await self._articles(session, role, category)
        if not visible_rows:
            return []

        portable_lexical = self._portable_lexical(visible_rows, normalized)
        if session.bind and session.bind.dialect.name == "postgresql":
            postgres_lexical = await self._postgres_lexical(
                session, role=role, query=normalized, category=category
            )
            merged: dict[UUID, tuple[float, str]] = {}
            for article_id, score, snippet in [*postgres_lexical, *portable_lexical]:
                previous = merged.get(article_id)
                if previous is None or score > previous[0]:
                    merged[article_id] = (score, snippet)
            lexical = sorted(
                [(article_id, score, snippet) for article_id, (score, snippet) in merged.items()],
                key=lambda item: item[1],
                reverse=True,
            )
        else:
            lexical = portable_lexical

        semantic: list[tuple[UUID, float, str]] = []
        try:
            vector = await nvidia_adapter.embed_query(normalized)
            semantic = await self._semantic(session, visible_rows, vector)
        except ModelUnavailableError:
            semantic = []

        rank: dict[UUID, float] = {}
        snippet_by_id: dict[UUID, str] = {}
        score_by_id: dict[UUID, float] = {}
        for position, (article_id, score, snippet) in enumerate(lexical[:candidate_limit], start=1):
            rank[article_id] = rank.get(article_id, 0.0) + 1.0 / (60 + position)
            score_by_id[article_id] = max(score_by_id.get(article_id, 0.0), score)
            snippet_by_id.setdefault(article_id, snippet)
        for position, (article_id, score, snippet) in enumerate(semantic[:candidate_limit], start=1):
            rank[article_id] = rank.get(article_id, 0.0) + 1.0 / (60 + position)
            previous_score = score_by_id.get(article_id, 0.0)
            if score > previous_score or article_id not in snippet_by_id:
                snippet_by_id[article_id] = snippet
            score_by_id[article_id] = max(previous_score, score)

        by_id = {article.id: (article, cat) for article, cat in visible_rows}
        normalized_cf = normalized.casefold()
        for article, _ in visible_rows:
            title_cf = article.title.casefold()
            if title_cf == normalized_cf:
                rank[article.id] = rank.get(article.id, 0.0) + 0.08
                score_by_id[article.id] = max(score_by_id.get(article.id, 0.0), 1.0)
            elif title_cf.startswith(normalized_cf):
                rank[article.id] = rank.get(article.id, 0.0) + 0.04
            if article.featured and article.id in rank:
                rank[article.id] += 0.002

        ordered = sorted(rank, key=lambda article_id: (rank[article_id], score_by_id.get(article_id, 0.0)), reverse=True)
        hits: list[HelpSearchHit] = []
        for article_id in ordered[:candidate_limit]:
            article, cat = by_id.get(article_id, (None, None))
            if article is None or cat is None:
                continue
            hits.append(
                HelpSearchHit(
                    article=article,
                    category=cat,
                    score=round(max(score_by_id.get(article_id, 0.0), min(1.0, rank[article_id] * 30)), 4),
                    snippet=snippet_by_id.get(article_id) or _snippet(article.summary or article.body_markdown, query_tokens),
                )
            )
        return hits

    async def _postgres_lexical(
        self,
        session: AsyncSession,
        *,
        role: Role,
        query: str,
        category: str | None,
    ) -> list[tuple[UUID, float, str]]:
        ts_query = func.websearch_to_tsquery("simple", query)
        vector = func.to_tsvector(
            "simple",
            HelpArticle.title + " " + HelpArticle.summary + " " + HelpArticle.body_markdown,
        )
        rank_expr = func.ts_rank_cd(vector, ts_query)
        statement = (
            select(HelpArticle, rank_expr.label("rank"))
            .join(HelpCategory, HelpCategory.id == HelpArticle.category_id)
            .where(
                HelpArticle.status == HelpArticleStatus.PUBLISHED,
                HelpCategory.is_active.is_(True),
                ts_query.op("@@")(vector),
            )
            .order_by(rank_expr.desc())
            .limit(self.settings.help_search_candidate_limit)
        )
        if category:
            statement = statement.where(HelpCategory.slug == category)
        rows = (await session.execute(statement)).all()
        role_value = role.value
        query_tokens = _tokens(query)
        return [
            (article.id, float(score), _snippet(article.body_markdown, query_tokens))
            for article, score in rows
            if role_value in (article.audience_roles_json or [])
        ]

    def _portable_lexical(
        self,
        rows: Iterable[tuple[HelpArticle, HelpCategory]],
        query: str,
    ) -> list[tuple[UUID, float, str]]:
        query_tokens = _tokens(query)
        query_cf = query.casefold()
        results: list[tuple[UUID, float, str]] = []
        for article, category in rows:
            title_tokens = _tokens(article.title)
            keyword_tokens = _tokens(" ".join(article.keywords_json or []))
            summary_tokens = _tokens(article.summary)
            body_tokens = _tokens(article.body_markdown)
            category_tokens = _tokens(category.title)
            title_overlap = len(query_tokens & title_tokens) / max(1, len(query_tokens))
            keyword_overlap = len(query_tokens & keyword_tokens) / max(1, len(query_tokens))
            summary_overlap = len(query_tokens & summary_tokens) / max(1, len(query_tokens))
            body_overlap = len(query_tokens & body_tokens) / max(1, len(query_tokens))
            category_overlap = len(query_tokens & category_tokens) / max(1, len(query_tokens))
            score = (
                title_overlap * 0.42
                + keyword_overlap * 0.24
                + summary_overlap * 0.16
                + body_overlap * 0.14
                + category_overlap * 0.04
            )
            if query_cf in article.title.casefold():
                score += 0.25
            elif query_cf in article.summary.casefold():
                score += 0.12
            if score > 0:
                results.append((article.id, min(1.0, score), _snippet(article.body_markdown, query_tokens)))
        return sorted(results, key=lambda item: item[1], reverse=True)

    async def _semantic(
        self,
        session: AsyncSession,
        visible_rows: list[tuple[HelpArticle, HelpCategory]],
        vector: list[float],
    ) -> list[tuple[UUID, float, str]]:
        allowed = {article.id for article, _ in visible_rows}
        if not allowed:
            return []
        if session.bind and session.bind.dialect.name == "postgresql":
            distance = HelpArticleChunk.embedding.cosine_distance(vector)
            rows = (
                await session.execute(
                    select(HelpArticleChunk, distance.label("distance"))
                    .where(HelpArticleChunk.article_id.in_(allowed), HelpArticleChunk.embedding.is_not(None))
                    .order_by(distance)
                    .limit(self.settings.help_search_candidate_limit)
                )
            ).all()
            best: dict[UUID, tuple[float, str]] = {}
            for chunk, dist in rows:
                score = max(0.0, 1.0 - float(dist))
                previous = best.get(chunk.article_id)
                if previous is None or score > previous[0]:
                    best[chunk.article_id] = (score, chunk.content)
            return sorted(
                [(article_id, score, _snippet(text, set())) for article_id, (score, text) in best.items()],
                key=lambda item: item[1],
                reverse=True,
            )

        chunks = (
            await session.scalars(select(HelpArticleChunk).where(HelpArticleChunk.article_id.in_(allowed)))
        ).all()
        best: dict[UUID, tuple[float, str]] = {}
        for chunk in chunks:
            if chunk.embedding is None:
                continue
            score = max(0.0, _cosine(vector, list(chunk.embedding)))
            previous = best.get(chunk.article_id)
            if previous is None or score > previous[0]:
                best[chunk.article_id] = (score, chunk.content)
        return sorted(
            [(article_id, score, _snippet(text, set())) for article_id, (score, text) in best.items()],
            key=lambda item: item[1],
            reverse=True,
        )

    async def evidence(
        self,
        session: AsyncSession,
        *,
        role: Role,
        question: str,
        limit: int = 6,
    ) -> list[HelpEvidence]:
        hits = await self.search(session, role=role, query=question, limit=max(limit, 10))
        if not hits:
            return []
        top_ids = [hit.article.id for hit in hits[:limit]]
        hit_score = {hit.article.id: hit.score for hit in hits}
        categories = {hit.article.id: hit.category for hit in hits}
        chunks = (
            await session.scalars(
                select(HelpArticleChunk)
                .where(HelpArticleChunk.article_id.in_(top_ids))
                .order_by(HelpArticleChunk.article_id, HelpArticleChunk.chunk_index)
            )
        ).all()
        query_tokens = _tokens(question)
        query_cf = question.strip().casefold()
        best_chunk: dict[UUID, tuple[float, HelpArticleChunk]] = {}
        for chunk in chunks:
            chunk_tokens = _tokens(chunk.content)
            overlap = len(query_tokens & chunk_tokens) / max(1, len(query_tokens))
            phrase_boost = 0.25 if query_cf and query_cf in chunk.content.casefold() else 0.0
            heading_boost = 0.08 if any(
                token in (chunk.heading_path or "").casefold() for token in query_tokens
            ) else 0.0
            score = overlap + phrase_boost + heading_boost - (chunk.chunk_index * 0.0001)
            previous = best_chunk.get(chunk.article_id)
            if previous is None or score > previous[0]:
                best_chunk[chunk.article_id] = (score, chunk)
        by_id = {hit.article.id: hit.article for hit in hits}
        evidence: list[HelpEvidence] = []
        for article_id in top_ids:
            selected = best_chunk.get(article_id)
            if selected is None:
                continue
            evidence.append(
                HelpEvidence(
                    article=by_id[article_id],
                    category=categories[article_id],
                    chunk=selected[1],
                    score=hit_score[article_id],
                )
            )
        return evidence


help_search_service = HelpSearchService()
