"""Interpret course and enrollment calendar dates in the workspace timezone."""

from datetime import UTC, date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.models import Workspace


def local_calendar_date(timezone: str | None, now: datetime | None = None) -> date:
    try:
        zone = ZoneInfo(timezone or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo("UTC")
    return (now or datetime.now(UTC)).astimezone(zone).date()


async def workspace_today(session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID) -> date:
    timezone = await session.scalar(
        select(Workspace.timezone).where(
            Workspace.id == workspace_id,
            Workspace.tenant_id == tenant_id,
        )
    )
    return local_calendar_date(timezone)
