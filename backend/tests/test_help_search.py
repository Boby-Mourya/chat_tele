from __future__ import annotations

from sqlalchemy import select

from northstar_api.database import SessionFactory
from northstar_api.help_models import HelpArticle
from northstar_api.models import Role
from northstar_api.services.help_search import help_search_service


async def test_help_search_respects_role_before_ranking(client) -> None:
    # client starts the lifespan and idempotently syncs docs-as-code content.
    await client.get('/health/live')
    async with SessionFactory() as session:
        owner_hits = await help_search_service.search(session, role=Role.OWNER, query='create agent')
        analyst_hits = await help_search_service.search(session, role=Role.ANALYST, query='create agent')
        assert any(hit.article.slug == 'create-agent' for hit in owner_hits)
        assert all(hit.article.slug != 'create-agent' for hit in analyst_hits)


async def test_help_search_exact_title_and_content_sync_are_stable(client) -> None:
    await client.get('/health/live')
    async with SessionFactory() as session:
        before = len((await session.scalars(select(HelpArticle))).all())
        hits = await help_search_service.search(session, role=Role.OWNER, query='Understand the Analytics dashboard')
        assert hits
        assert hits[0].article.slug == 'analytics-dashboard'
        after = len((await session.scalars(select(HelpArticle))).all())
        assert before == after
