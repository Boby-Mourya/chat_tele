from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.lead_crm.audit import record_audit_event
from northstar_api.lead_crm.dead_letter_schemas import CRMDeadLetterOut, CRMDeadLetterReplayOut
from northstar_api.lead_crm.models import CRMDelivery, IntegrationDeadLetter
from northstar_api.models import Lead
from northstar_api.security import Principal

router = APIRouter(prefix="/crm/dead-letters", tags=["crm"])
DB = Annotated[AsyncSession, Depends(get_session)]
CRMViewPrincipal = Annotated[Principal, Depends(require_permissions("crm.view"))]
CRMManagePrincipal = Annotated[Principal, Depends(require_permissions("crm.manage"))]
DeadLetterStatus = Literal["open", "resolved", "all"]


@router.get("", response_model=list[CRMDeadLetterOut])
async def list_crm_dead_letters(
    principal: CRMViewPrincipal,
    session: DB,
    connection_id: UUID | None = Query(default=None),
    dead_letter_status: DeadLetterStatus = Query(default="open", alias="status"),
) -> list[CRMDeadLetterOut]:
    """List dead letters that resolve through a Lead in the active Workspace."""

    if principal.workspace_id is None:
        raise HTTPException(status_code=403, detail="Workspace access is unavailable")

    conditions = [
        IntegrationDeadLetter.tenant_id == principal.tenant_id,
        CRMDelivery.tenant_id == principal.tenant_id,
        Lead.tenant_id == principal.tenant_id,
        Lead.workspace_id == principal.workspace_id,
    ]
    if connection_id is not None:
        conditions.append(CRMDelivery.connection_id == connection_id)
    if dead_letter_status != "all":
        conditions.append(IntegrationDeadLetter.status == dead_letter_status)

    rows = list(
        await session.execute(
            select(IntegrationDeadLetter, CRMDelivery)
            .join(CRMDelivery, CRMDelivery.id == IntegrationDeadLetter.delivery_id)
            .join(Lead, Lead.id == CRMDelivery.lead_id)
            .where(*conditions)
            .order_by(IntegrationDeadLetter.created_at.desc())
            .limit(200)
        )
    )
    return [
        CRMDeadLetterOut(
            id=dead_letter.id,
            delivery_id=delivery.id,
            lead_id=delivery.lead_id,
            connection_id=delivery.connection_id,
            provider=delivery.provider,
            status=dead_letter.status,
            reason_code=dead_letter.reason_code,
            reason_message=dead_letter.reason_message,
            created_at=dead_letter.created_at,
            updated_at=dead_letter.updated_at,
            resolved_at=dead_letter.resolved_at,
        )
        for dead_letter, delivery in rows
    ]


@router.post("/{dead_letter_id}/replay", response_model=CRMDeadLetterReplayOut)
async def replay_crm_dead_letter(
    dead_letter_id: UUID,
    principal: CRMManagePrincipal,
    session: DB,
) -> CRMDeadLetterReplayOut:
    """Resolve one open DLQ incident while queueing the existing delivery retry atomically."""

    if principal.workspace_id is None:
        raise HTTPException(status_code=403, detail="Workspace access is unavailable")

    row = (
        await session.execute(
            select(IntegrationDeadLetter, CRMDelivery)
            .join(CRMDelivery, CRMDelivery.id == IntegrationDeadLetter.delivery_id)
            .join(Lead, Lead.id == CRMDelivery.lead_id)
            .where(
                IntegrationDeadLetter.id == dead_letter_id,
                IntegrationDeadLetter.tenant_id == principal.tenant_id,
                CRMDelivery.tenant_id == principal.tenant_id,
                Lead.tenant_id == principal.tenant_id,
                Lead.workspace_id == principal.workspace_id,
            )
            .with_for_update()
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="CRM dead letter not found in this workspace")

    dead_letter, delivery = row
    if dead_letter.status != "open":
        raise HTTPException(status_code=409, detail="CRM dead letter has already been resolved")
    if delivery.status != "dead_letter":
        raise HTTPException(status_code=409, detail="CRM delivery is no longer in dead-letter state")

    replayed_at = datetime.now(UTC)
    metadata = dict(dead_letter.metadata_json or {})
    metadata["resolution"] = {
        "type": "replay_requested",
        "userId": str(principal.user_id),
        "at": replayed_at.isoformat(),
    }
    dead_letter.metadata_json = metadata
    dead_letter.status = "resolved"
    dead_letter.resolved_at = replayed_at
    record_audit_event(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id,
        action="crm.dead_letter.replayed",
        entity_type="crm_dead_letter",
        entity_id=str(dead_letter.id),
        category="crm",
        severity="warning",
        before={"status": "open", "deliveryStatus": "dead_letter"},
        after={"status": "resolved", "deliveryStatus": "retrying"},
        metadata={
            "deliveryId": str(delivery.id),
            "leadId": str(delivery.lead_id),
            "connectionId": str(delivery.connection_id),
        },
    )

    # Reuse the existing workspace-scoped retry endpoint. Its commit flushes the
    # dead-letter resolution and retry transition together in the same transaction.
    from northstar_api.routers.crm_scoped import retry_crm_delivery

    retry_result = await retry_crm_delivery(delivery.id, principal, session)
    delivery_status = str(getattr(retry_result.status, "value", retry_result.status))
    return CRMDeadLetterReplayOut(
        dead_letter_id=dead_letter.id,
        delivery_id=delivery.id,
        dead_letter_status=dead_letter.status,
        delivery_status=delivery_status,
        replayed_at=replayed_at,
    )
