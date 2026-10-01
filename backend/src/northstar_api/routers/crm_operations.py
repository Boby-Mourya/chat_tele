from __future__ import annotations

from collections import Counter
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.lead_crm.models import CRMConnection, CRMDelivery, IntegrationDeadLetter
from northstar_api.lead_crm.operations_health_schemas import (
    CRMOperationalConnectionHealthOut,
    CRMOperationalHealthOut,
)
from northstar_api.lead_crm.workspace_scope import WorkspaceCRMConnection
from northstar_api.models import Lead
from northstar_api.security import Principal

router = APIRouter(prefix="/crm/operations", tags=["crm"])
DB = Annotated[AsyncSession, Depends(get_session)]
CRMViewPrincipal = Annotated[Principal, Depends(require_permissions("crm.view"))]

_PENDING_STATUSES = frozenset({"created", "routed", "queued", "processing", "sent", "acknowledged", "verifying"})
_RETRYING_STATUSES = frozenset({"retrying", "rate_limited"})
_FAILED_STATUSES = frozenset({"auth_required", "mapping_error", "failed", "dead_letter"})
_ATTENTION_CONNECTION_STATUSES = frozenset(
    {"degraded", "unhealthy", "auth_required", "rate_limited", "configuration_error", "disabled"}
)


def _connection_needs_attention(row: CRMOperationalConnectionHealthOut) -> bool:
    return (
        row.status in _ATTENTION_CONNECTION_STATUSES
        or row.failed_deliveries > 0
        or row.open_dead_letters > 0
    )


@router.get("/health", response_model=CRMOperationalHealthOut)
async def crm_operational_health(
    principal: CRMViewPrincipal,
    session: DB,
) -> CRMOperationalHealthOut:
    """Summarize current CRM operational state for the active Workspace."""

    if principal.workspace_id is None:
        raise HTTPException(status_code=403, detail="Workspace access is unavailable")

    connections = list(
        await session.scalars(
            select(CRMConnection)
            .join(WorkspaceCRMConnection, WorkspaceCRMConnection.connection_id == CRMConnection.id)
            .where(
                CRMConnection.tenant_id == principal.tenant_id,
                WorkspaceCRMConnection.tenant_id == principal.tenant_id,
                WorkspaceCRMConnection.workspace_id == principal.workspace_id,
            )
            .order_by(CRMConnection.created_at, CRMConnection.id)
        )
    )
    connection_ids = [connection.id for connection in connections]

    delivery_counts: dict[UUID, Counter[str]] = {}
    dead_letter_counts: Counter[UUID] = Counter()
    if connection_ids:
        delivery_rows = list(
            await session.execute(
                select(CRMDelivery.connection_id, CRMDelivery.status)
                .join(Lead, Lead.id == CRMDelivery.lead_id)
                .where(
                    CRMDelivery.tenant_id == principal.tenant_id,
                    Lead.tenant_id == principal.tenant_id,
                    Lead.workspace_id == principal.workspace_id,
                    CRMDelivery.connection_id.in_(connection_ids),
                )
            )
        )
        for connection_id, status in delivery_rows:
            delivery_counts.setdefault(connection_id, Counter())[status] += 1

        dead_letter_rows = list(
            await session.execute(
                select(CRMDelivery.connection_id)
                .join(IntegrationDeadLetter, IntegrationDeadLetter.delivery_id == CRMDelivery.id)
                .join(Lead, Lead.id == CRMDelivery.lead_id)
                .where(
                    IntegrationDeadLetter.tenant_id == principal.tenant_id,
                    IntegrationDeadLetter.status == "open",
                    CRMDelivery.tenant_id == principal.tenant_id,
                    Lead.tenant_id == principal.tenant_id,
                    Lead.workspace_id == principal.workspace_id,
                    CRMDelivery.connection_id.in_(connection_ids),
                )
            )
        )
        dead_letter_counts.update(row[0] for row in dead_letter_rows)

    rows: list[CRMOperationalConnectionHealthOut] = []
    for connection in connections:
        counts = delivery_counts.get(connection.id, Counter())
        pending = sum(counts[status] for status in _PENDING_STATUSES)
        retrying = sum(counts[status] for status in _RETRYING_STATUSES)
        failed = sum(counts[status] for status in _FAILED_STATUSES)
        rows.append(
            CRMOperationalConnectionHealthOut(
                connection_id=connection.id,
                name=connection.name,
                provider=connection.provider,
                status=connection.status,
                last_health_at=connection.last_health_at,
                last_success_at=connection.last_success_at,
                last_failure_at=connection.last_failure_at,
                last_error=connection.last_error,
                pending_deliveries=pending,
                retrying_deliveries=retrying,
                failed_deliveries=failed,
                open_dead_letters=dead_letter_counts[connection.id],
            )
        )

    attention_connections = sum(1 for row in rows if _connection_needs_attention(row))
    healthy_connections = sum(
        1 for row in rows if row.status == "healthy" and not _connection_needs_attention(row)
    )
    pending_total = sum(row.pending_deliveries for row in rows)
    retrying_total = sum(row.retrying_deliveries for row in rows)
    failed_total = sum(row.failed_deliveries for row in rows)
    dead_letter_total = sum(row.open_dead_letters for row in rows)
    has_nonhealthy_nonattention_connection = any(
        row.status != "healthy" and not _connection_needs_attention(row) for row in rows
    )

    if not rows:
        overall_status = "empty"
    elif attention_connections:
        overall_status = "attention"
    elif retrying_total or pending_total or has_nonhealthy_nonattention_connection:
        overall_status = "active"
    else:
        overall_status = "healthy"

    return CRMOperationalHealthOut(
        overall_status=overall_status,
        connection_count=len(rows),
        healthy_connections=healthy_connections,
        attention_connections=attention_connections,
        pending_deliveries=pending_total,
        retrying_deliveries=retrying_total,
        failed_deliveries=failed_total,
        open_dead_letters=dead_letter_total,
        connections=rows,
    )
