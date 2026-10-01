from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.lead_crm.models import CRMWebhookEvent
from northstar_api.lead_crm.webhook_event_schemas import CRMWebhookEventOut
from northstar_api.lead_crm.workspace_scope import WorkspaceCRMConnection
from northstar_api.security import Principal

router = APIRouter(prefix="/crm/webhook-events", tags=["crm"])
DB = Annotated[AsyncSession, Depends(get_session)]
CRMViewPrincipal = Annotated[Principal, Depends(require_permissions("crm.view"))]


@router.get("", response_model=list[CRMWebhookEventOut])
async def list_crm_webhook_events(
    principal: CRMViewPrincipal,
    session: DB,
    connection_id: UUID | None = Query(default=None),
    processing_status: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=100, ge=1, le=200),
) -> list[CRMWebhookEventOut]:
    """List safe inbound CRM webhook processing evidence for the active Workspace."""

    if principal.workspace_id is None:
        raise HTTPException(status_code=403, detail="Workspace access is unavailable")

    conditions = [
        CRMWebhookEvent.tenant_id == principal.tenant_id,
        WorkspaceCRMConnection.tenant_id == principal.tenant_id,
        WorkspaceCRMConnection.workspace_id == principal.workspace_id,
    ]
    if connection_id is not None:
        conditions.append(CRMWebhookEvent.connection_id == connection_id)
    if processing_status:
        conditions.append(CRMWebhookEvent.processing_status == processing_status)

    values = list(
        await session.scalars(
            select(CRMWebhookEvent)
            .join(
                WorkspaceCRMConnection,
                WorkspaceCRMConnection.connection_id == CRMWebhookEvent.connection_id,
            )
            .where(*conditions)
            .order_by(CRMWebhookEvent.received_at.desc(), CRMWebhookEvent.id.desc())
            .limit(limit)
        )
    )
    return [
        CRMWebhookEventOut(
            id=value.id,
            connection_id=value.connection_id,
            provider=value.provider,
            event_type=value.event_type,
            verification_status=value.verification_status,
            processing_status=value.processing_status,
            correlation_id=value.correlation_id,
            received_at=value.received_at,
            processed_at=value.processed_at,
            last_error=value.last_error,
        )
        for value in values
    ]
