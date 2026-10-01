from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.lead_crm.audit import record_audit_event
from northstar_api.lead_crm.channel_models import ChannelConnection
from northstar_api.lead_crm.channel_scope import WorkspaceChannelConnection
from northstar_api.lead_crm.channel_webhook_event_schemas import ChannelWebhookEventOut
from northstar_api.lead_crm.models import RawWebhookEvent
from northstar_api.models import Agent
from northstar_api.security import Principal
from northstar_api.services.outbox import enqueue_event

router = APIRouter(prefix="/channels/webhook-events", tags=["channels"])
DB = Annotated[AsyncSession, Depends(get_session)]
ChannelsViewPrincipal = Annotated[Principal, Depends(require_permissions("integrations.view"))]
ChannelsManagePrincipal = Annotated[Principal, Depends(require_permissions("integrations.manage"))]
_REPLAYABLE_FAILURE_CODES = frozenset({"agent_not_configured"})


def _error_code(processing_status: str) -> str | None:
    if processing_status == "failed":
        return "processing_failed"
    if processing_status == "rejected":
        return "processing_rejected"
    return None


def _can_requeue(value: RawWebhookEvent) -> bool:
    return value.processing_status == "failed" and value.last_error in _REPLAYABLE_FAILURE_CODES


def _out(value: RawWebhookEvent) -> ChannelWebhookEventOut:
    return ChannelWebhookEventOut(
        id=value.id,
        connection_id=UUID(value.connection_key),
        provider=value.provider,
        event_type=value.event_type,
        verification_status=value.verification_status,
        processing_status=value.processing_status,
        attempt_count=value.attempt_count,
        error_code=_error_code(value.processing_status),
        can_requeue=_can_requeue(value),
        correlation_id=value.correlation_id,
        received_at=value.received_at,
        processed_at=value.processed_at,
    )


@router.get("", response_model=list[ChannelWebhookEventOut])
async def list_channel_webhook_events(
    principal: ChannelsViewPrincipal,
    session: DB,
    connection_id: UUID | None = Query(default=None),
    processing_status: str | None = Query(default=None, max_length=40),
    provider: str | None = Query(default=None, max_length=60),
    limit: int = Query(default=100, ge=1, le=200),
) -> list[ChannelWebhookEventOut]:
    """List safe inbound webhook processing evidence for the active Workspace."""

    if principal.workspace_id is None:
        raise HTTPException(status_code=403, detail="Workspace access is unavailable")

    connection_query = (
        select(ChannelConnection.id)
        .join(
            WorkspaceChannelConnection,
            WorkspaceChannelConnection.connection_id == ChannelConnection.id,
        )
        .where(
            ChannelConnection.tenant_id == principal.tenant_id,
            WorkspaceChannelConnection.tenant_id == principal.tenant_id,
            WorkspaceChannelConnection.workspace_id == principal.workspace_id,
        )
    )
    if connection_id is not None:
        connection_query = connection_query.where(ChannelConnection.id == connection_id)

    connection_ids = list(await session.scalars(connection_query))
    if connection_id is not None and not connection_ids:
        raise HTTPException(status_code=404, detail="Channel connection not found in this workspace")
    if not connection_ids:
        return []

    query = select(RawWebhookEvent).where(
        RawWebhookEvent.tenant_id == principal.tenant_id,
        RawWebhookEvent.connection_key.in_([str(value) for value in connection_ids]),
    )
    if processing_status:
        query = query.where(RawWebhookEvent.processing_status == processing_status)
    if provider:
        query = query.where(RawWebhookEvent.provider == provider)

    values = list(
        await session.scalars(
            query.order_by(RawWebhookEvent.received_at.desc(), RawWebhookEvent.id.desc()).limit(limit)
        )
    )
    return [_out(value) for value in values]


@router.post("/{event_id}/requeue", response_model=ChannelWebhookEventOut)
async def requeue_failed_channel_webhook(
    event_id: UUID,
    principal: ChannelsManagePrincipal,
    session: DB,
) -> ChannelWebhookEventOut:
    """Requeue only the known pre-side-effect channel configuration failure."""

    if principal.workspace_id is None:
        raise HTTPException(status_code=403, detail="Workspace access is unavailable")

    raw = await session.scalar(
        select(RawWebhookEvent)
        .where(
            RawWebhookEvent.id == event_id,
            RawWebhookEvent.tenant_id == principal.tenant_id,
        )
        .with_for_update()
    )
    if raw is None:
        raise HTTPException(status_code=404, detail="Channel webhook event not found in this workspace")

    try:
        connection_id = UUID(raw.connection_key)
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail="Channel webhook event is not attached to a replayable channel connection",
        ) from exc

    scoped = (
        await session.execute(
            select(ChannelConnection, WorkspaceChannelConnection)
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
            .with_for_update()
        )
    ).first()
    if scoped is None:
        raise HTTPException(status_code=404, detail="Channel webhook event not found in this workspace")
    connection, scope = scoped

    if not _can_requeue(raw):
        raise HTTPException(
            status_code=409,
            detail="Only replayable failed channel webhook events can be manually requeued",
        )
    if connection.status == "disabled":
        raise HTTPException(status_code=409, detail="Channel connection must be enabled before requeue")

    raw_agent_id = connection.configuration_json.get("agentId")
    try:
        agent_id = UUID(str(raw_agent_id))
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=409,
            detail="Channel connection must configure a valid agent before requeue",
        ) from exc

    agent = await session.scalar(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.tenant_id == principal.tenant_id,
            Agent.workspace_id == principal.workspace_id,
            Agent.deleted_at.is_(None),
        )
    )
    if agent is None or (scope.agent_id is not None and scope.agent_id != agent.id):
        raise HTTPException(
            status_code=409,
            detail="Channel connection agent must belong to this workspace before requeue",
        )

    before_attempt_count = raw.attempt_count
    raw.processing_status = "received"
    raw.processed_at = None
    raw.last_error = None
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="raw_webhook_event",
        aggregate_id=raw.id,
        event_type="channel.event.received.v1",
        payload={
            "rawEventId": str(raw.id),
            "provider": raw.provider,
            "workspaceId": str(principal.workspace_id),
            "agentId": str(agent.id),
            "channelConnectionId": str(connection.id),
        },
    )
    record_audit_event(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id,
        action="channel.webhook.failed_requeued",
        entity_type="raw_webhook_event",
        entity_id=str(raw.id),
        category="channel",
        severity="warning",
        before={
            "processingStatus": "failed",
            "errorCode": "agent_not_configured",
            "attemptCount": before_attempt_count,
        },
        after={
            "processingStatus": "received",
            "errorCode": None,
            "attemptCount": before_attempt_count,
        },
        metadata={
            "connectionId": str(connection.id),
            "provider": raw.provider,
            "agentId": str(agent.id),
        },
    )
    await session.commit()
    await session.refresh(raw)
    return _out(raw)
