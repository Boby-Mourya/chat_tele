from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.lead_crm.channel_health_history_schemas import ChannelHealthSnapshotOut
from northstar_api.lead_crm.channel_models import ChannelConnection, ChannelHealthSnapshot
from northstar_api.lead_crm.channel_scope import WorkspaceChannelConnection
from northstar_api.security import Principal

router = APIRouter(prefix="/channels/connections", tags=["channels"])
DB = Annotated[AsyncSession, Depends(get_session)]
ChannelsViewPrincipal = Annotated[Principal, Depends(require_permissions("integrations.view"))]


async def _scoped_connection(
    session: AsyncSession,
    principal: Principal,
    connection_id: UUID,
) -> ChannelConnection | None:
    if principal.workspace_id is None:
        return None
    return await session.scalar(
        select(ChannelConnection)
        .join(
            WorkspaceChannelConnection,
            WorkspaceChannelConnection.connection_id == ChannelConnection.id,
        )
        .where(
            ChannelConnection.id == connection_id,
            ChannelConnection.tenant_id == principal.tenant_id,
            WorkspaceChannelConnection.tenant_id == principal.tenant_id,
            WorkspaceChannelConnection.workspace_id == principal.workspace_id,
        )
    )


def _snapshot_out(value: ChannelHealthSnapshot) -> ChannelHealthSnapshotOut:
    return ChannelHealthSnapshotOut(
        id=value.id,
        connection_id=value.connection_id,
        status=value.status,
        error_code=value.error_code,
        checked_at=value.checked_at,
    )


@router.get("/{connection_id}/health-history", response_model=list[ChannelHealthSnapshotOut])
async def list_channel_health_history(
    connection_id: UUID,
    principal: ChannelsViewPrincipal,
    session: DB,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ChannelHealthSnapshotOut]:
    """Return recent safe scheduled-health history for one channel in the active Workspace."""

    connection = await _scoped_connection(session, principal, connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="Channel connection not found in this workspace")

    values = list(
        await session.scalars(
            select(ChannelHealthSnapshot)
            .where(
                ChannelHealthSnapshot.tenant_id == principal.tenant_id,
                ChannelHealthSnapshot.connection_id == connection.id,
            )
            .order_by(ChannelHealthSnapshot.checked_at.desc(), ChannelHealthSnapshot.id.desc())
            .limit(limit)
        )
    )
    return [_snapshot_out(value) for value in values]
