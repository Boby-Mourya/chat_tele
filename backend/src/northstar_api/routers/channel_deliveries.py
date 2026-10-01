from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.lead_crm.audit import record_audit_event
from northstar_api.lead_crm.channel_delivery_schemas import (
    ChannelDeliveryAttemptOut,
    ChannelOutboundDeliveryOut,
)
from northstar_api.lead_crm.channel_models import (
    ChannelConnection,
    ChannelDeliveryAttempt,
    ChannelOutboundDelivery,
)
from northstar_api.lead_crm.channel_scope import WorkspaceChannelConnection
from northstar_api.security import Principal

router = APIRouter(prefix="/channels/deliveries", tags=["channels"])
DB = Annotated[AsyncSession, Depends(get_session)]
ChannelsViewPrincipal = Annotated[Principal, Depends(require_permissions("integrations.view"))]
ChannelsManagePrincipal = Annotated[Principal, Depends(require_permissions("integrations.manage"))]


def _error_code(status: str) -> str | None:
    if status == "failed":
        return "retryable_failure"
    if status in {"rejected", "reconnect_required", "dispatch_failed"}:
        return status
    return None


def _out(
    delivery: ChannelOutboundDelivery,
    connection_name: str | None,
) -> ChannelOutboundDeliveryOut:
    return ChannelOutboundDeliveryOut(
        id=delivery.id,
        connection_id=delivery.connection_id,
        connection_name=connection_name,
        message_id=delivery.message_id,
        provider=delivery.provider,
        status=delivery.status,
        error_code=_error_code(delivery.status),
        attempt_count=delivery.attempt_count,
        dispatch_attempts=delivery.dispatch_attempts,
        dispatched_at=delivery.dispatched_at,
        processed_at=delivery.processed_at,
        next_dispatch_at=delivery.next_dispatch_at,
        created_at=delivery.created_at,
        updated_at=delivery.updated_at,
    )


@router.get("", response_model=list[ChannelOutboundDeliveryOut])
async def list_channel_deliveries(
    principal: ChannelsViewPrincipal,
    session: DB,
    connection_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=100, ge=1, le=200),
) -> list[ChannelOutboundDeliveryOut]:
    """List safe outbound delivery evidence for the active Workspace."""

    if principal.workspace_id is None:
        raise HTTPException(status_code=403, detail="Workspace access is unavailable")

    if connection_id is not None:
        owned = await session.scalar(
            select(ChannelConnection.id)
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
        if owned is None:
            raise HTTPException(status_code=404, detail="Channel connection not found in this workspace")

    query = (
        select(ChannelOutboundDelivery, ChannelConnection.name)
        .outerjoin(ChannelConnection, ChannelConnection.id == ChannelOutboundDelivery.connection_id)
        .outerjoin(
            WorkspaceChannelConnection,
            WorkspaceChannelConnection.connection_id == ChannelOutboundDelivery.connection_id,
        )
        .where(
            ChannelOutboundDelivery.tenant_id == principal.tenant_id,
            ChannelOutboundDelivery.workspace_id == principal.workspace_id,
            or_(
                ChannelOutboundDelivery.connection_id.is_(None),
                and_(
                    WorkspaceChannelConnection.tenant_id == principal.tenant_id,
                    WorkspaceChannelConnection.workspace_id == principal.workspace_id,
                ),
            ),
        )
    )
    if connection_id is not None:
        query = query.where(ChannelOutboundDelivery.connection_id == connection_id)
    if status:
        query = query.where(ChannelOutboundDelivery.status == status)

    rows = (
        await session.execute(
            query.order_by(
                ChannelOutboundDelivery.updated_at.desc(),
                ChannelOutboundDelivery.id.desc(),
            ).limit(limit)
        )
    ).all()
    return [_out(delivery, connection_name) for delivery, connection_name in rows]


@router.get("/{delivery_id}/attempts", response_model=list[ChannelDeliveryAttemptOut])
async def list_channel_delivery_attempts(
    delivery_id: UUID,
    principal: ChannelsViewPrincipal,
    session: DB,
    limit: int = Query(default=100, ge=1, le=200),
) -> list[ChannelDeliveryAttemptOut]:
    """List safe immutable attempt evidence for one delivery in the active Workspace."""

    if principal.workspace_id is None:
        raise HTTPException(status_code=403, detail="Workspace access is unavailable")

    visible_delivery = await session.scalar(
        select(ChannelOutboundDelivery.id)
        .outerjoin(ChannelConnection, ChannelConnection.id == ChannelOutboundDelivery.connection_id)
        .outerjoin(
            WorkspaceChannelConnection,
            WorkspaceChannelConnection.connection_id == ChannelOutboundDelivery.connection_id,
        )
        .where(
            ChannelOutboundDelivery.id == delivery_id,
            ChannelOutboundDelivery.tenant_id == principal.tenant_id,
            ChannelOutboundDelivery.workspace_id == principal.workspace_id,
            or_(
                ChannelOutboundDelivery.connection_id.is_(None),
                and_(
                    ChannelConnection.tenant_id == principal.tenant_id,
                    WorkspaceChannelConnection.tenant_id == principal.tenant_id,
                    WorkspaceChannelConnection.workspace_id == principal.workspace_id,
                ),
            ),
        )
    )
    if visible_delivery is None:
        raise HTTPException(status_code=404, detail="Channel delivery not found in this workspace")

    attempts = list(
        await session.scalars(
            select(ChannelDeliveryAttempt)
            .where(
                ChannelDeliveryAttempt.tenant_id == principal.tenant_id,
                ChannelDeliveryAttempt.workspace_id == principal.workspace_id,
                ChannelDeliveryAttempt.delivery_id == delivery_id,
            )
            .order_by(
                ChannelDeliveryAttempt.created_at.desc(),
                ChannelDeliveryAttempt.id.desc(),
            )
            .limit(limit)
        )
    )
    return [
        ChannelDeliveryAttemptOut(
            id=attempt.id,
            delivery_id=attempt.delivery_id,
            phase=attempt.phase,
            attempt_number=attempt.attempt_number,
            outcome=attempt.outcome,
            error_code=attempt.error_code,
            created_at=attempt.created_at,
        )
        for attempt in attempts
    ]


@router.post("/{delivery_id}/requeue", response_model=ChannelOutboundDeliveryOut)
async def requeue_channel_dispatch_failure(
    delivery_id: UUID,
    principal: ChannelsManagePrincipal,
    session: DB,
) -> ChannelOutboundDeliveryOut:
    """Reset only an exhausted broker-dispatch failure for the existing dispatcher."""

    if principal.workspace_id is None:
        raise HTTPException(status_code=403, detail="Workspace access is unavailable")

    row = (
        await session.execute(
            select(ChannelOutboundDelivery, ChannelConnection)
            .join(ChannelConnection, ChannelConnection.id == ChannelOutboundDelivery.connection_id)
            .join(
                WorkspaceChannelConnection,
                WorkspaceChannelConnection.connection_id == ChannelConnection.id,
            )
            .where(
                ChannelOutboundDelivery.id == delivery_id,
                ChannelOutboundDelivery.tenant_id == principal.tenant_id,
                ChannelOutboundDelivery.workspace_id == principal.workspace_id,
                ChannelConnection.tenant_id == principal.tenant_id,
                WorkspaceChannelConnection.tenant_id == principal.tenant_id,
                WorkspaceChannelConnection.workspace_id == principal.workspace_id,
            )
            .with_for_update()
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Channel delivery not found in this workspace")

    delivery, connection = row
    if delivery.status != "dispatch_failed":
        raise HTTPException(
            status_code=409,
            detail="Only dispatch_failed channel deliveries can be manually requeued",
        )
    if connection.status in {
        "disabled",
        "reconnect_required",
        "auth_required",
        "configuration_error",
    }:
        raise HTTPException(
            status_code=409,
            detail="Channel connection must be operational before requeue",
        )

    before_dispatch_attempts = delivery.dispatch_attempts
    now = datetime.now(UTC)
    delivery.status = "queued"
    delivery.dispatch_attempts = 0
    delivery.dispatched_at = None
    delivery.next_dispatch_at = now
    delivery.last_error = None
    record_audit_event(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id,
        action="channel.delivery.dispatch_requeued",
        entity_type="channel_outbound_delivery",
        entity_id=str(delivery.id),
        category="channel",
        severity="warning",
        before={
            "status": "dispatch_failed",
            "dispatchAttempts": before_dispatch_attempts,
        },
        after={
            "status": "queued",
            "dispatchAttempts": 0,
            "nextDispatchAt": now.isoformat(),
        },
        metadata={
            "connectionId": str(connection.id),
            "provider": delivery.provider,
            "messageId": str(delivery.message_id),
        },
    )
    await session.commit()
    await session.refresh(delivery)
    return _out(delivery, connection.name)
