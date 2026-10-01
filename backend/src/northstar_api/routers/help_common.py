from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import select

from northstar_api.dependencies import DBSession
from northstar_api.help_models import (
    HelpArticle,
    HelpArticleStatus,
    HelpCategory,
    HelpEvent,
    HelpSupportRequest,
)
from northstar_api.help_schemas import (
    HelpArticleSummaryOut,
    HelpCategoryOut,
    HelpSupportDestinationOut,
    HelpSupportRequestCreate,
    HelpSupportRequestOut,
)
from northstar_api.models import Role, Tenant

_SAFE_DIAGNOSTIC_KEYS = {"userAgent", "appVersion", "buildId", "platform", "language", "timezone"}
_SECRET_KEY_PATTERN = re.compile(r"token|secret|password|authorization|cookie|api.?key|credential", re.I)


def _sanitize_diagnostics(payload: HelpSupportRequestCreate) -> dict[str, str]:
    if not payload.include_diagnostics:
        return {}
    return {
        key: value[:500]
        for key, value in payload.diagnostics.items()
        if key in _SAFE_DIAGNOSTIC_KEYS and not _SECRET_KEY_PATTERN.search(key)
    }


def _support_out(row: HelpSupportRequest) -> HelpSupportRequestOut:
    return HelpSupportRequestOut(
        id=row.id,
        category=row.category,
        subject=row.subject,
        message=row.message,
        status=row.status,
        context_path=row.context_path,
        requester_email=row.requester_email,
        support_destination=row.support_destination,
        diagnostics=row.diagnostics_json or {},
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _role_visible(article: HelpArticle, role: Role) -> bool:
    return role.value in (article.audience_roles_json or [])


def _summary(article: HelpArticle, category: HelpCategory) -> HelpArticleSummaryOut:
    return HelpArticleSummaryOut(
        id=article.id,
        slug=article.slug,
        category_slug=category.slug,
        category_title=category.title,
        title=article.title,
        summary=article.summary,
        keywords=list(article.keywords_json or []),
        reading_minutes=article.reading_minutes,
        updated_at=article.updated_at,
        featured=article.featured,
        audience_roles=[Role(value) for value in article.audience_roles_json or []],
    )


async def _support_destination(session: DBSession, tenant_id: UUID) -> HelpSupportDestinationOut:
    tenant = await session.scalar(select(Tenant).where(Tenant.id == tenant_id))
    settings_json: dict[str, Any] = tenant.settings_json if tenant and tenant.settings_json else {}
    white_label = settings_json.get("whiteLabel") if isinstance(settings_json, dict) else {}
    if not isinstance(white_label, dict):
        white_label = {}
    email = str(white_label.get("supportEmail") or "support@northstar.ai").strip()
    external_candidate = str(white_label.get("supportUrl") or "").strip()
    parsed = urlparse(external_candidate) if external_candidate else None
    external_url = (
        external_candidate if parsed and parsed.scheme in {"http", "https"} and parsed.netloc else ""
    )
    return HelpSupportDestinationOut(email=email, external_url=external_url)


async def _published_rows(session: DBSession, role: Role) -> list[tuple[HelpArticle, HelpCategory]]:
    rows = (
        await session.execute(
            select(HelpArticle, HelpCategory)
            .join(HelpCategory, HelpCategory.id == HelpArticle.category_id)
            .where(HelpArticle.status == HelpArticleStatus.PUBLISHED, HelpCategory.is_active.is_(True))
            .order_by(HelpCategory.sort_order, HelpArticle.sort_order, HelpArticle.title)
        )
    ).all()
    return [(article, category) for article, category in rows if _role_visible(article, role)]


def _category_payload(category: HelpCategory, count: int) -> HelpCategoryOut:
    return HelpCategoryOut(
        id=category.id,
        slug=category.slug,
        title=category.title,
        description=category.description,
        icon=category.icon,
        article_count=count,
        sort_order=category.sort_order,
    )


async def _record_event(
    session: DBSession,
    principal: Any,
    event_type: str,
    *,
    article_id: UUID | None = None,
    query: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    session.add(
        HelpEvent(
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            article_id=article_id,
            event_type=event_type,
            query=query[:300] if query else None,
            metadata_json=metadata or {},
        )
    )
