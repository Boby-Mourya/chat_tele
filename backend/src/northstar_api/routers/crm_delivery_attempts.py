from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.lead_crm.delivery_attempt_schemas import CRMDeliveryAttemptOut
from northstar_api.lead_crm.models import CRMDelivery, CRMDeliveryAttempt
from northstar_api.models import Lead
from northstar_api.security import Principal

router = APIRouter(prefix="/crm/deliveries", tags=["crm"])
DB = Annotated[AsyncSession, Depends(get_session)]
LeadViewPrincipal = Annotated[Principal, Depends(require_permissions("leads.view"))]


@router.get("/{delivery_id}/attempts", response_model=list[CRMDeliveryAttemptOut])
async def list_crm_delivery_attempts(
    delivery_id: UUID,
    principal: LeadViewPrincipal,
    session: DB,
) -> list[CRMDeliveryAttemptOut]:
    """Return safe attempt evidence for one delivery in the active Workspace."""

    if principal.workspace_id is None:
        raise HTTPException(status_code=403, detail="Workspace access is unavailable")

    delivery = await session.scalar(
        select(CRMDelivery.id)
        .join(Lead, Lead.id == CRMDelivery.lead_id)
        .where(
            CRMDelivery.id == delivery_id,
            CRMDelivery.tenant_id == principal.tenant_id,
            Lead.tenant_id == principal.tenant_id,
            Lead.workspace_id == principal.workspace_id,
        )
    )
    if delivery is None:
        raise HTTPException(status_code=404, detail="CRM delivery not found")

    attempts = list(
        await session.scalars(
            select(CRMDeliveryAttempt)
            .where(
                CRMDeliveryAttempt.tenant_id == principal.tenant_id,
                CRMDeliveryAttempt.delivery_id == delivery_id,
            )
            .order_by(CRMDeliveryAttempt.attempt_number.asc())
        )
    )
    return [
        CRMDeliveryAttemptOut(
            id=attempt.id,
            delivery_id=attempt.delivery_id,
            attempt_number=attempt.attempt_number,
            started_at=attempt.started_at,
            finished_at=attempt.finished_at,
            http_status=attempt.http_status,
            latency_ms=attempt.latency_ms,
            result_status=attempt.result_status,
            normalized_error_code=attempt.normalized_error_code,
            provider_error_code=attempt.provider_error_code,
            provider_request_id=attempt.provider_request_id,
        )
        for attempt in attempts
    ]