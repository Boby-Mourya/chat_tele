from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from northstar_api.config import Settings, get_settings
from northstar_api.education_knowledge_lifecycle import (
    EducationKnowledgeRelease,
    EducationReleaseAssignment,
)
from northstar_api.education_knowledge_scope import EducationKnowledgeScope
from northstar_api.metrics import RETRIEVAL_DURATION, RETRIEVAL_EVIDENCE
from northstar_api.models import (
    DocumentChunk,
    FactStatus,
    KnowledgeFact,
    KnowledgeSource,
    KnowledgeStatus,
)
from northstar_api.services.llm import NvidiaModelAdapter, nvidia_adapter


@dataclass(frozen=True, slots=True)
class Evidence:
    kind: str
    entity_id: str
    source_id: str | None
    title: str
    url: str | None
    text: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)
    dense_score: float | None = None
    lexical_score: float | None = None
    fusion_score: float | None = None


@dataclass(frozen=True, slots=True)
class EducationRetrievalScope:
    workspace_id: UUID
    student_id: UUID
    enrollment_id: UUID
    course_id: UUID
    batch_id: UUID
    curriculum_id: UUID | None = None
    paper_id: UUID | None = None


class RetrievalService:
    def __init__(
        self,
        model: NvidiaModelAdapter | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.model = model or nvidia_adapter
        self.settings = settings or get_settings()

    async def retrieve(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        agent_id: UUID,
        revision: int,
        query: str,
        education_scope: EducationRetrievalScope | None = None,
        rerank_candidates: int | None = None,
        final_context_chunks: int | None = None,
    ) -> list[Evidence]:
        started = time.perf_counter()
        # Vectorless RAG: retrieval must not call an embedding provider.
        evidence = await self._portable_retrieve(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            revision=revision,
            query=query,
            education_scope=education_scope,
            candidate_limit=rerank_candidates,
        )
        if education_scope is not None:
            evidence = await self._filter_assignment_blocks(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                scope=education_scope,
                evidence=evidence,
            )
        evidence = _rerank(
            evidence,
            query,
            final_context_chunks or self.settings.retrieval_context_limit,
        )
        RETRIEVAL_DURATION.observe(time.perf_counter() - started)
        RETRIEVAL_EVIDENCE.observe(len(evidence))
        return evidence

    @staticmethod
    def _active_release_filter(scope: EducationRetrievalScope) -> ColumnElement[bool]:
        membership = exists(
            select(EducationReleaseAssignment.id)
            .join(
                EducationKnowledgeRelease,
                EducationKnowledgeRelease.id == EducationReleaseAssignment.release_id,
            )
            .where(
                EducationReleaseAssignment.assignment_id == EducationKnowledgeScope.id,
                EducationReleaseAssignment.assignment_revision
                == EducationKnowledgeScope.assignment_revision,
                EducationKnowledgeRelease.workspace_id == scope.workspace_id,
                EducationKnowledgeRelease.course_id == scope.course_id,
                EducationKnowledgeRelease.curriculum_id == scope.curriculum_id,
                EducationKnowledgeRelease.status == "active",
                EducationKnowledgeRelease.index_verified.is_(True),
            )
        )
        return or_(EducationKnowledgeScope.requires_release.is_(False), membership)

    @staticmethod
    async def _filter_assignment_blocks(
        session: AsyncSession,
        *,
        tenant_id: UUID,
        agent_id: UUID,
        scope: EducationRetrievalScope,
        evidence: list[Evidence],
    ) -> list[Evidence]:
        """Enforce section-level grants before evidence enters model context.

        The search backend applies the coarse tuple filter.  This second,
        authoritative gate is needed for a source that contains independently
        permissioned blocks. Missing block provenance fails closed.
        """
        if not evidence:
            return []
        conditions: list[ColumnElement[bool]] = [
            EducationKnowledgeScope.tenant_id == tenant_id,
            EducationKnowledgeScope.workspace_id == scope.workspace_id,
            EducationKnowledgeScope.agent_id == agent_id,
            EducationKnowledgeScope.course_id == scope.course_id,
            EducationKnowledgeScope.approval_status == "published",
            EducationKnowledgeScope.withdrawn_at.is_(None),
            RetrievalService._active_release_filter(scope),
            or_(
                EducationKnowledgeScope.batch_id.is_(None),
                EducationKnowledgeScope.batch_id == scope.batch_id,
            ),
        ]
        if scope.curriculum_id is not None:
            conditions.append(
                or_(
                    EducationKnowledgeScope.curriculum_id == scope.curriculum_id,
                    (
                        EducationKnowledgeScope.curriculum_id.is_(None)
                        & (EducationKnowledgeScope.batch_id == scope.batch_id)
                    ),
                )
            )
        if scope.paper_id is None:
            conditions.append(EducationKnowledgeScope.paper_id.is_(None))
        else:
            conditions.append(
                or_(
                    EducationKnowledgeScope.paper_id.is_(None),
                    EducationKnowledgeScope.paper_id == scope.paper_id,
                )
            )
        assignments = (await session.scalars(select(EducationKnowledgeScope).where(*conditions))).all()
        by_source: dict[str, list[EducationKnowledgeScope]] = {}
        by_fact: dict[str, list[EducationKnowledgeScope]] = {}
        for assignment in assignments:
            if assignment.source_id is not None:
                by_source.setdefault(str(assignment.source_id), []).append(assignment)
            if assignment.fact_id is not None:
                by_fact.setdefault(str(assignment.fact_id), []).append(assignment)

        allowed: list[Evidence] = []
        for item in evidence:
            grants = list(by_fact.get(item.entity_id, ()))
            if item.source_id:
                grants.extend(by_source.get(item.source_id, ()))
            block_id = next(
                (
                    str(item.metadata[key])
                    for key in ("blockId", "block_id", "sourceBlockId", "source_block_id")
                    if item.metadata.get(key) is not None
                ),
                None,
            )
            if any(
                not grant.selected_block_ids
                or (block_id is not None and block_id in grant.selected_block_ids)
                for grant in grants
            ):
                allowed.append(item)
        return allowed

    @staticmethod
    def _source_scope_filter(
        *,
        tenant_id: UUID,
        agent_id: UUID,
        source_id: Any,
        scope: EducationRetrievalScope,
    ) -> ColumnElement[bool]:
        conditions: list[ColumnElement[bool]] = [
            EducationKnowledgeScope.tenant_id == tenant_id,
            EducationKnowledgeScope.workspace_id == scope.workspace_id,
            EducationKnowledgeScope.agent_id == agent_id,
            EducationKnowledgeScope.source_id == source_id,
            EducationKnowledgeScope.course_id == scope.course_id,
            EducationKnowledgeScope.approval_status == "published",
            EducationKnowledgeScope.withdrawn_at.is_(None),
            RetrievalService._active_release_filter(scope),
            or_(
                EducationKnowledgeScope.batch_id.is_(None),
                EducationKnowledgeScope.batch_id == scope.batch_id,
            ),
        ]
        if scope.curriculum_id is not None:
            conditions.append(
                or_(
                    EducationKnowledgeScope.curriculum_id == scope.curriculum_id,
                    (
                        EducationKnowledgeScope.curriculum_id.is_(None)
                        & (EducationKnowledgeScope.batch_id == scope.batch_id)
                    ),
                )
            )
        if scope.paper_id is not None:
            conditions.append(
                or_(
                    EducationKnowledgeScope.paper_id.is_(None),
                    EducationKnowledgeScope.paper_id == scope.paper_id,
                )
            )
        else:
            # A missing paper selection is deliberately *not* an "all papers"
            # wildcard.  Only explicitly course-wide overview material is safe
            # until the learner selects (or the tutor resolves) a paper.
            conditions.append(EducationKnowledgeScope.paper_id.is_(None))
        return exists(select(EducationKnowledgeScope.id).where(*conditions))

    @classmethod
    def _fact_scope_filter(
        cls,
        *,
        tenant_id: UUID,
        agent_id: UUID,
        scope: EducationRetrievalScope,
    ) -> ColumnElement[bool]:
        direct_conditions: list[ColumnElement[bool]] = [
            EducationKnowledgeScope.tenant_id == tenant_id,
            EducationKnowledgeScope.workspace_id == scope.workspace_id,
            EducationKnowledgeScope.agent_id == agent_id,
            EducationKnowledgeScope.fact_id == KnowledgeFact.id,
            EducationKnowledgeScope.course_id == scope.course_id,
            EducationKnowledgeScope.approval_status == "published",
            EducationKnowledgeScope.withdrawn_at.is_(None),
            cls._active_release_filter(scope),
            or_(
                EducationKnowledgeScope.batch_id.is_(None),
                EducationKnowledgeScope.batch_id == scope.batch_id,
            ),
        ]
        if scope.curriculum_id is not None:
            direct_conditions.append(
                or_(
                    EducationKnowledgeScope.curriculum_id == scope.curriculum_id,
                    (
                        EducationKnowledgeScope.curriculum_id.is_(None)
                        & (EducationKnowledgeScope.batch_id == scope.batch_id)
                    ),
                )
            )
        if scope.paper_id is not None:
            direct_conditions.append(
                or_(
                    EducationKnowledgeScope.paper_id.is_(None),
                    EducationKnowledgeScope.paper_id == scope.paper_id,
                )
            )
        else:
            direct_conditions.append(EducationKnowledgeScope.paper_id.is_(None))
        direct = exists(select(EducationKnowledgeScope.id).where(*direct_conditions))
        inherited = cls._source_scope_filter(
            tenant_id=tenant_id,
            agent_id=agent_id,
            source_id=KnowledgeFact.source_id,
            scope=scope,
        )
        return or_(direct, inherited)

    async def _postgres_retrieve(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        agent_id: UUID,
        revision: int,
        query: str,
        education_scope: EducationRetrievalScope | None,
        candidate_limit: int | None,
    ) -> list[Evidence]:
        # LEGACY PGVECTOR PATH — intentionally inactive and retained only for
        # historical-reference compatibility. Do not call from vectorless RAG.
        # `retrieve()` always uses `_portable_retrieve()` above, so normal PDF
        # knowledge uses vectorless lexical retrieval and never calls this
        # dense cosine-distance implementation.
        limit = candidate_limit or self.settings.retrieval_candidate_limit
        fact_filters = [
            KnowledgeFact.tenant_id == tenant_id,
            KnowledgeFact.agent_id == agent_id,
            KnowledgeFact.status == FactStatus.APPROVED,
            KnowledgeFact.revision <= revision,
        ]
        chunk_filters = [
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.agent_id == agent_id,
            DocumentChunk.approved.is_(True),
            DocumentChunk.revision <= revision,
        ]
        if education_scope is not None:
            fact_filters.extend(
                [
                    KnowledgeFact.workspace_id == education_scope.workspace_id,
                    self._fact_scope_filter(
                        tenant_id=tenant_id,
                        agent_id=agent_id,
                        scope=education_scope,
                    ),
                ]
            )
            chunk_filters.extend(
                [
                    DocumentChunk.workspace_id == education_scope.workspace_id,
                    self._source_scope_filter(
                        tenant_id=tenant_id,
                        agent_id=agent_id,
                        source_id=DocumentChunk.source_id,
                        scope=education_scope,
                    ),
                ]
            )

        # Legacy pgvector cosine search (kept only as commented/inactive
        # compatibility code; no active retrieval path reaches it).
        fact_distance = KnowledgeFact.embedding.cosine_distance(vector)
        fact_dense = (
            select(KnowledgeFact, KnowledgeSource.name, KnowledgeSource.url, fact_distance.label("distance"))
            .outerjoin(KnowledgeSource, KnowledgeSource.id == KnowledgeFact.source_id)
            .where(
                *fact_filters,
                KnowledgeFact.embedding.is_not(None),
                or_(KnowledgeSource.id.is_(None), KnowledgeSource.status == KnowledgeStatus.READY),
            )
            .order_by(fact_distance)
            .limit(limit)
        )
        chunk_distance = DocumentChunk.embedding.cosine_distance(vector)
        chunk_dense = (
            select(DocumentChunk, KnowledgeSource.name, KnowledgeSource.url, chunk_distance.label("distance"))
            .join(KnowledgeSource, KnowledgeSource.id == DocumentChunk.source_id)
            .where(
                *chunk_filters,
                DocumentChunk.embedding.is_not(None),
                KnowledgeSource.status == KnowledgeStatus.READY,
            )
            .order_by(chunk_distance)
            .limit(limit)
        )
        rank: dict[tuple[str, str], float] = {}
        candidates: dict[tuple[str, str], Evidence] = {}
        for kind, result in (
            ("fact", await session.execute(fact_dense)),
            ("chunk", await session.execute(chunk_dense)),
        ):
            for position, row in enumerate(result.all(), start=1):
                entity, title, url, distance = row
                key = (kind, str(entity.id))
                rank[key] = rank.get(key, 0) + 1 / (60 + position)
                text = f"Q: {entity.question}\nA: {entity.answer}" if kind == "fact" else entity.content
                candidates[key] = Evidence(
                    kind=kind,
                    entity_id=str(entity.id),
                    source_id=str(entity.source_id) if entity.source_id else None,
                    title=title or ("Verified Q&A" if kind == "fact" else "Knowledge base"),
                    url=url,
                    text=text,
                    score=max(0.0, 1.0 - float(distance)),
                    metadata=(entity.metadata_json if kind == "chunk" else entity.source_span) or {},
                    dense_score=max(0.0, 1.0 - float(distance)),
                )

        ts_query = func.websearch_to_tsquery("simple", query)
        fact_rank = func.ts_rank_cd(
            func.to_tsvector("simple", KnowledgeFact.question + " " + KnowledgeFact.answer), ts_query
        )
        fact_lexical = (
            select(KnowledgeFact, KnowledgeSource.name, KnowledgeSource.url, fact_rank.label("rank"))
            .outerjoin(KnowledgeSource, KnowledgeSource.id == KnowledgeFact.source_id)
            .where(
                *fact_filters,
                or_(KnowledgeSource.id.is_(None), KnowledgeSource.status == KnowledgeStatus.READY),
                ts_query.op("@@")(
                    func.to_tsvector("simple", KnowledgeFact.question + " " + KnowledgeFact.answer)
                ),
            )
            .order_by(fact_rank.desc())
            .limit(limit)
        )
        chunk_rank = func.ts_rank_cd(func.to_tsvector("simple", DocumentChunk.content), ts_query)
        chunk_lexical = (
            select(DocumentChunk, KnowledgeSource.name, KnowledgeSource.url, chunk_rank.label("rank"))
            .join(KnowledgeSource, KnowledgeSource.id == DocumentChunk.source_id)
            .where(
                *chunk_filters,
                KnowledgeSource.status == KnowledgeStatus.READY,
                ts_query.op("@@")(func.to_tsvector("simple", DocumentChunk.content)),
            )
            .order_by(chunk_rank.desc())
            .limit(limit)
        )
        for kind, result in (
            ("fact", await session.execute(fact_lexical)),
            ("chunk", await session.execute(chunk_lexical)),
        ):
            for position, row in enumerate(result.all(), start=1):
                entity, title, url, lexical_score = row
                key = (kind, str(entity.id))
                rank[key] = rank.get(key, 0) + 1 / (60 + position)
                if key not in candidates:
                    text = f"Q: {entity.question}\nA: {entity.answer}" if kind == "fact" else entity.content
                    candidates[key] = Evidence(
                        kind=kind,
                        entity_id=str(entity.id),
                        source_id=str(entity.source_id) if entity.source_id else None,
                        title=title or ("Verified Q&A" if kind == "fact" else "Knowledge base"),
                        url=url,
                        text=text,
                        score=float(lexical_score),
                        metadata=(entity.metadata_json if kind == "chunk" else entity.source_span) or {},
                        lexical_score=float(lexical_score),
                    )
                else:
                    candidates[key] = replace_evidence(
                        candidates[key], candidates[key].score, lexical_score=float(lexical_score)
                    )
        max_rrf = 2 / 61
        candidates = {
            key: replace_evidence(item, rank[key] / max_rrf, fusion_score=rank[key] / max_rrf)
            for key, item in candidates.items()
            if item.dense_score is None
            or item.dense_score >= self.settings.retrieval_min_score
            or item.lexical_score is not None
        }
        ordered = sorted(
            candidates.values(),
            key=lambda item: (rank[(item.kind, item.entity_id)], item.score),
            reverse=True,
        )
        if not ordered:
            return []
        return ordered

    async def _portable_retrieve(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        agent_id: UUID,
        revision: int,
        query: str,
        education_scope: EducationRetrievalScope | None,
        candidate_limit: int | None,
    ) -> list[Evidence]:
        fact_filters = [
            KnowledgeFact.tenant_id == tenant_id,
            KnowledgeFact.agent_id == agent_id,
            KnowledgeFact.status == FactStatus.APPROVED,
            KnowledgeFact.revision <= revision,
        ]
        chunk_filters = [
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.agent_id == agent_id,
            DocumentChunk.approved.is_(True),
            DocumentChunk.revision <= revision,
        ]
        if education_scope is not None:
            fact_filters.extend(
                [
                    KnowledgeFact.workspace_id == education_scope.workspace_id,
                    self._fact_scope_filter(
                        tenant_id=tenant_id,
                        agent_id=agent_id,
                        scope=education_scope,
                    ),
                ]
            )
            chunk_filters.extend(
                [
                    DocumentChunk.workspace_id == education_scope.workspace_id,
                    self._source_scope_filter(
                        tenant_id=tenant_id,
                        agent_id=agent_id,
                        source_id=DocumentChunk.source_id,
                        scope=education_scope,
                    ),
                ]
            )

        # `candidate_limit` is the number of ranked candidates to retain, not
        # a limit on the unordered database rows inspected.  Applying it to
        # the raw query could hide a newer source behind the first pages of a
        # different PDF before lexical scoring even began.
        scan_limit = max(candidate_limit or 0, self.settings.knowledge_max_chunks)
        fact_rows = (
            await session.execute(
                select(KnowledgeFact, KnowledgeSource.name, KnowledgeSource.url)
                .outerjoin(KnowledgeSource, KnowledgeSource.id == KnowledgeFact.source_id)
                .where(
                    *fact_filters,
                    or_(KnowledgeSource.id.is_(None), KnowledgeSource.status == KnowledgeStatus.READY),
                )
                .limit(scan_limit)
            )
        ).all()
        chunk_rows = (
            await session.execute(
                select(DocumentChunk, KnowledgeSource.name, KnowledgeSource.url)
                .join(KnowledgeSource, KnowledgeSource.id == DocumentChunk.source_id)
                .where(*chunk_filters, KnowledgeSource.status == KnowledgeStatus.READY)
                .limit(scan_limit)
            )
        ).all()
        # Score against the question terms, not against every word in a full
        # document chunk.  Jaccard similarity (intersection / union) makes a
        # genuine match in a long PDF look close to zero, which incorrectly
        # rejects valid vectorless evidence at the configured minimum score.
        stop_words = {
            "a", "an", "and", "are", "as", "at", "be", "by", "do", "does",
            "for", "from", "how", "i", "in", "is", "it", "of", "on", "or",
            "the", "to", "was", "what", "when", "where", "which", "who", "why",
            "with", "would",
        }
        query_words = {
            word for word in re.findall(r"\w+", query.casefold()) if word not in stop_words
        }
        if not query_words:
            query_words = set(re.findall(r"\w+", query.casefold()))
        candidates: list[Evidence] = []
        for kind, rows in (("fact", fact_rows), ("chunk", chunk_rows)):
            for entity, title, url in rows:
                text = f"Q: {entity.question}\nA: {entity.answer}" if kind == "fact" else entity.content
                words = set(re.findall(r"\w+", text.casefold()))
                lexical = len(query_words & words) / max(1, len(query_words))
                score = lexical
                if score >= self.settings.retrieval_min_score:
                    candidates.append(
                        Evidence(
                            kind=kind,
                            entity_id=str(entity.id),
                            source_id=str(entity.source_id) if entity.source_id else None,
                            title=title or ("Verified Q&A" if kind == "fact" else "Knowledge base"),
                            url=url,
                            text=text,
                            score=score,
                            metadata=(entity.metadata_json if kind == "chunk" else entity.source_span) or {},
                            lexical_score=lexical,
                            fusion_score=score,
                        )
                    )
        if not candidates:
            return []
        # A generic term (for example, "cells") can occur in an unrelated
        # source. Keep evidence that is close to the best query-coverage
        # match, rather than letting a weak partial match dilute the grounded
        # context with another document.
        best_score = max(item.score for item in candidates)
        relevance_floor = max(self.settings.retrieval_min_score, best_score * 0.75)
        return sorted(
            (item for item in candidates if item.score >= relevance_floor),
            key=lambda item: item.score,
            reverse=True,
        )


def _cosine(left: list[float], right: list[float]) -> float:
    # Legacy helper for the inactive pgvector fusion implementation above.
    # Vectorless RAG does not call this function.
    if not left or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norm_left = math.sqrt(sum(value * value for value in left))
    norm_right = math.sqrt(sum(value * value for value in right))
    return dot / (norm_left * norm_right) if norm_left and norm_right else 0.0


def _rerank(evidence: list[Evidence], query: str, limit: int) -> list[Evidence]:
    """Cheap deterministic reranking after vectorless lexical retrieval.

    Exact terms and critical qualifiers receive a small boost. This improves
    latency versus a second model call while keeping numbers and NOT/EXCEPT
    visible to the ranking decision.
    """
    query_terms = set(re.findall(r"\w+", query.casefold()))
    critical = set(re.findall(r"\b(?:not|except|least|most|incorrect)\b", query.casefold()))
    scored: list[tuple[float, Evidence]] = []
    seen_sources: set[str] = set()
    for item in evidence:
        terms = set(re.findall(r"\w+", item.text.casefold()))
        overlap = len(query_terms & terms) / max(1, len(query_terms))
        critical_overlap = len(critical & terms) / max(1, len(critical)) if critical else 0.0
        diversity_bonus = 0.015 if item.source_id not in seen_sources else 0.0
        score = item.score + (0.08 * overlap) + (0.30 * critical_overlap) + diversity_bonus
        scored.append((score, item))
        if item.source_id:
            seen_sources.add(item.source_id)
    scored.sort(key=lambda value: value[0], reverse=True)
    return [replace_evidence(item, score) for score, item in scored[: max(1, limit)]]


def replace_evidence(
    item: Evidence,
    score: float,
    *,
    lexical_score: float | None = None,
    fusion_score: float | None = None,
) -> Evidence:
    return Evidence(
        kind=item.kind,
        entity_id=item.entity_id,
        source_id=item.source_id,
        title=item.title,
        url=item.url,
        text=item.text,
        score=score,
        metadata=item.metadata,
        dense_score=item.dense_score,
        lexical_score=item.lexical_score if lexical_score is None else lexical_score,
        fusion_score=item.fusion_score if fusion_score is None else fusion_score,
    )


retrieval_service = RetrievalService()
