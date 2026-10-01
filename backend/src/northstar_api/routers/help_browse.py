from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from northstar_api.dependencies import CurrentPrincipal, DBSession
from northstar_api.help_config import get_help_settings
from northstar_api.help_models import HelpArticle, HelpArticleStatus, HelpCategory, HelpEvent
from northstar_api.help_schemas import HelpArticleOut, HelpCategoryDetailOut, HelpCategoryOut, HelpHomeOut, HelpSearchPageOut, HelpSearchResultOut
from northstar_api.routers.help_common import _category_payload, _published_rows, _record_event, _role_visible, _summary, _support_destination
from northstar_api.services.help_search import HelpSearchHit, help_search_service

router = APIRouter()
settings = get_help_settings()

@router.get("", response_model=HelpHomeOut)
async def help_home(
    principal: CurrentPrincipal,
    session: DBSession,
    context: Annotated[str | None, Query(alias="from", max_length=80)] = None,
) -> HelpHomeOut:
    rows = await _published_rows(session, principal.role)
    category_rows = (await session.scalars(select(HelpCategory).where(HelpCategory.is_active.is_(True)).order_by(HelpCategory.sort_order))).all()
    counts: dict[UUID, int] = {}
    for article, category in rows:
        counts[category.id] = counts.get(category.id, 0) + 1
    categories = [_category_payload(category, counts.get(category.id, 0)) for category in category_rows if counts.get(category.id, 0)]
    view_rows = (
        await session.execute(
            select(HelpEvent.article_id, func.count(HelpEvent.id))
            .where(
                HelpEvent.tenant_id == principal.tenant_id,
                HelpEvent.event_type == "view",
                HelpEvent.article_id.is_not(None),
            )
            .group_by(HelpEvent.article_id)
        )
    ).all()
    view_counts = {article_id: int(count) for article_id, count in view_rows if article_id}
    ranked_rows = sorted(
        rows,
        key=lambda item: (
            1 if item[0].featured else 0,
            view_counts.get(item[0].id, 0),
            -item[1].sort_order,
            -item[0].sort_order,
        ),
        reverse=True,
    )
    popular = [_summary(article, category) for article, category in ranked_rows[:8]]
    normalized_context = (context or "").strip().casefold()
    recommended_rows = ranked_rows
    if normalized_context:
        contextual = [
            (article, category)
            for article, category in rows
            if normalized_context == category.slug.casefold()
            or normalized_context in article.title.casefold()
            or normalized_context in " ".join(article.keywords_json or []).casefold()
        ]
        if contextual:
            recommended_rows = sorted(
                contextual,
                key=lambda item: (
                    1 if item[0].featured else 0,
                    view_counts.get(item[0].id, 0),
                    -item[0].sort_order,
                ),
                reverse=True,
            )
    recommended = [_summary(article, category) for article, category in recommended_rows[:6]]
    return HelpHomeOut(
        categories=categories,
        popular=popular,
        recommended=recommended,
        support=await _support_destination(session, principal.tenant_id),
    )


@router.get("/categories", response_model=list[HelpCategoryOut])
async def help_categories(principal: CurrentPrincipal, session: DBSession) -> list[HelpCategoryOut]:
    rows = await _published_rows(session, principal.role)
    count_by_category: dict[UUID, int] = {}
    for _, category in rows:
        count_by_category[category.id] = count_by_category.get(category.id, 0) + 1
    categories = (await session.scalars(select(HelpCategory).where(HelpCategory.is_active.is_(True)).order_by(HelpCategory.sort_order))).all()
    return [_category_payload(category, count_by_category.get(category.id, 0)) for category in categories if count_by_category.get(category.id, 0)]


@router.get("/categories/{slug}", response_model=HelpCategoryDetailOut)
async def help_category(slug: str, principal: CurrentPrincipal, session: DBSession) -> HelpCategoryDetailOut:
    category = await session.scalar(select(HelpCategory).where(HelpCategory.slug == slug, HelpCategory.is_active.is_(True)))
    if not category:
        raise HTTPException(status_code=404, detail="Help category not found")
    articles = (
        await session.scalars(
            select(HelpArticle)
            .where(HelpArticle.category_id == category.id, HelpArticle.status == HelpArticleStatus.PUBLISHED)
            .order_by(HelpArticle.sort_order, HelpArticle.title)
        )
    ).all()
    visible = [article for article in articles if _role_visible(article, principal.role)]
    if not visible:
        raise HTTPException(status_code=404, detail="Help category not found")
    return HelpCategoryDetailOut(
        category=_category_payload(category, len(visible)),
        articles=[_summary(article, category) for article in visible],
    )


@router.get("/articles/{slug}", response_model=HelpArticleOut)
async def help_article(slug: str, principal: CurrentPrincipal, session: DBSession) -> HelpArticleOut:
    row = (
        await session.execute(
            select(HelpArticle, HelpCategory)
            .join(HelpCategory, HelpCategory.id == HelpArticle.category_id)
            .where(HelpArticle.slug == slug)
        )
    ).first()
    if not row or row[0].status != HelpArticleStatus.PUBLISHED or not row[1].is_active:
        raise HTTPException(status_code=404, detail="Help article not found")
    article, category = row
    if not _role_visible(article, principal.role):
        raise HTTPException(status_code=403, detail="This guide is not available for your workspace role")

    related_rows = (
        await session.execute(
            select(HelpArticle, HelpCategory)
            .join(HelpCategory, HelpCategory.id == HelpArticle.category_id)
            .where(
                HelpArticle.status == HelpArticleStatus.PUBLISHED,
                HelpArticle.id != article.id,
                HelpCategory.is_active.is_(True),
            )
            .order_by(HelpArticle.featured.desc(), HelpArticle.sort_order, HelpArticle.title)
        )
    ).all()
    article_keywords = set(article.keywords_json or [])
    related_rows = [
        item for item in related_rows
        if _role_visible(item[0], principal.role)
        and (item[0].category_id == article.category_id or bool(article_keywords & set(item[0].keywords_json or [])))
    ][:5]

    category_articles = (
        await session.scalars(
            select(HelpArticle)
            .where(
                HelpArticle.category_id == article.category_id,
                HelpArticle.status == HelpArticleStatus.PUBLISHED,
            )
            .order_by(HelpArticle.sort_order, HelpArticle.title)
        )
    ).all()
    visible_category_articles = [item for item in category_articles if _role_visible(item, principal.role)]
    current_index = next((index for index, item in enumerate(visible_category_articles) if item.id == article.id), -1)
    previous_article = visible_category_articles[current_index - 1] if current_index > 0 else None
    next_article = (
        visible_category_articles[current_index + 1]
        if current_index >= 0 and current_index + 1 < len(visible_category_articles)
        else None
    )

    await _record_event(session, principal, "view", article_id=article.id)
    await session.commit()
    base = _summary(article, category)
    return HelpArticleOut(
        **base.model_dump(),
        body_markdown=article.body_markdown,
        related=[_summary(item, cat) for item, cat in related_rows],
        previous=_summary(previous_article, category) if previous_article else None,
        next=_summary(next_article, category) if next_article else None,
    )


@router.get("/search", response_model=HelpSearchPageOut)
async def help_search(
    principal: CurrentPrincipal,
    session: DBSession,
    q: Annotated[str, Query(min_length=2, max_length=300)],
    category: Annotated[str | None, Query(max_length=100)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1)] = 20,
) -> HelpSearchPageOut:
    normalized = q.strip()
    if len(normalized) < 2:
        raise HTTPException(status_code=422, detail="Search query must be at least 2 characters")
    page_size = min(page_size, settings.help_search_page_size_max)
    if category:
        valid_category = await session.scalar(select(HelpCategory).where(HelpCategory.slug == category, HelpCategory.is_active.is_(True)))
        if not valid_category:
            raise HTTPException(status_code=404, detail="Help category not found")
    hits = await help_search_service.search(session, role=principal.role, query=normalized, category=category, limit=settings.help_search_candidate_limit)
    total = len(hits)
    start = (page - 1) * page_size
    page_hits = hits[start:start + page_size]
    await _record_event(session, principal, "search", query=normalized, metadata={"resultCount": total, "category": category or ""})
    await session.commit()
    return HelpSearchPageOut(
        items=[_search_result(hit) for hit in page_hits],
        total=total,
        page=page,
        page_size=page_size,
        query=normalized,
        suggested_category=(hits[0].category.slug if not category and hits else None),
    )


def _search_result(hit: HelpSearchHit) -> HelpSearchResultOut:
    base = _summary(hit.article, hit.category)
    return HelpSearchResultOut(**base.model_dump(), score=hit.score, snippet=hit.snippet)
