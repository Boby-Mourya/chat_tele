from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.lead_crm.connectors import CRMError
from northstar_api.lead_crm.integration_health_history_schemas import CRMHealthSnapshotOut
from northstar_api.lead_crm.models import CRMConnection, IntegrationHealthSnapshot
from northstar_api.lead_crm.workspace_scope import WorkspaceCRMConnection
from northstar_api.routers import crm as legacy_crm
from northstar_api.security import Principal

router = APIRouter(prefix="/crm/connections", tags=["crm"])
DB = Annotated[AsyncSession, Depends(get_session)]
CRMViewPrincipal = Annotated[Principal, Depends(require_permissions("crm.view"))]
CRMManagePrincipal = Annotated[Principal, Depends(require_permissions("crm.manage"))]

_SENSITIVE_CHECK_KEYS = {
    "accesstoken",
    "apikey",
    "authorization",
    "clientsecret",
    "cookie",
    "refreshtoken",
    "secret",
    "token",
}


async def _scoped_connection(
    session: AsyncSession,
    principal: Principal,
    connection_id: UUID,
) -> CRMConnection | None:
    if principal.workspace_id is None:
        return None
    return await session.scalar(
        select(CRMConnection)
        .join(WorkspaceCRMConnection, WorkspaceCRMConnection.connection_id == CRMConnection.id)
        .where(
            CRMConnection.id == connection_id,
            CRMConnection.tenant_id == principal.tenant_id,
            WorkspaceCRMConnection.tenant_id == principal.tenant_id,
            WorkspaceCRMConnection.workspace_id == principal.workspace_id,
        )
    )


def _sensitive_check_key(value: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", value.lower())
    return any(normalized == key or normalized.endswith(key) for key in _SENSITIVE_CHECK_KEYS)


def _safe_checks(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    safe: dict[str, str] = {}
    for key, item in value.items():
        label = str(key)[:80]
        safe[label] = "[REDACTED]" if _sensitive_check_key(label) else str(item)[:160]
    return safe


def _failure_checks(status: str) -> dict[str, str]:
    if status == "auth_required":
        return {"credentials": "reconnect_required"}
    if status == "configuration_error":
        return {"connector": "configuration_error"}
    return {"healthCheck": "failed"}


async def _persist_snapshot(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    connection_id: UUID,
    status: str,
    checks: dict[str, str],
    latency_ms: int | None,
) -> IntegrationHealthSnapshot:
    snapshot = IntegrationHealthSnapshot(
        tenant_id=tenant_id,
        connection_id=connection_id,
        status=status[:40],
        checks_json=checks,
        latency_ms=latency_ms,
        checked_at=datetime.now(UTC),
    )
    session.add(snapshot)
    await session.flush()
    return snapshot


def _snapshot_out(value: IntegrationHealthSnapshot) -> CRMHealthSnapshotOut:
    return CRMHealthSnapshotOut(
        id=value.id,
        connection_id=value.connection_id,
        status=value.status,
        checks=_safe_checks(value.checks_json),
        latency_ms=value.latency_ms,
        checked_at=value.checked_at,
    )


@router.post("/{connection_id}/health-check", response_model=CRMHealthSnapshotOut)
async def run_crm_health_check(
    connection_id: UUID,
    principal: CRMManagePrincipal,
    session: DB,
) -> CRMHealthSnapshotOut:
    """Run the existing CRM connection test and retain a safe historical snapshot."""

    connection = await _scoped_connection(session, principal, connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="CRM connection not found in this workspace")

    try:
        result: dict[str, Any] = await legacy_crm.test_crm_connection(
            connection_id,
            principal,
            session,
        )
    except HTTPException:
        await session.refresh(connection)
        snapshot = await _persist_snapshot(
            session,
            tenant_id=principal.tenant_id,
            connection_id=connection.id,
            status=connection.status,
            checks=_failure_checks(connection.status),
            latency_ms=None,
        )
        await session.commit()
        await session.refresh(snapshot)
        raise
    except CRMError:
        snapshot = await _persist_snapshot(
            session,
            tenant_id=principal.tenant_id,
            connection_id=connection.id,
            status="unhealthy",
            checks={"healthCheck": "provider_error"},
            latency_ms=None,
        )
        await session.commit()
        await session.refresh(snapshot)
        raise

    raw_latency = result.get("latencyMs")
    latency_ms = raw_latency if isinstance(raw_latency, int) and not isinstance(raw_latency, bool) else None
    snapshot = await _persist_snapshot(
        session,
        tenant_id=principal.tenant_id,
        connection_id=connection.id,
        status=str(result.get("status") or connection.status),
        checks=_safe_checks(result.get("checks")),
        latency_ms=latency_ms,
    )
    await session.commit()
    await session.refresh(snapshot)
    return _snapshot_out(snapshot)


@router.get("/{connection_id}/health-history", response_model=list[CRMHealthSnapshotOut])
async def list_crm_health_history(
    connection_id: UUID,
    principal: CRMViewPrincipal,
    session: DB,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[CRMHealthSnapshotOut]:
    """Return recent safe health-check history for one CRM in the active Workspace."""

    connection = await _scoped_connection(session, principal, connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="CRM connection not found in this workspace")

    values = list(
        await session.scalars(
            select(IntegrationHealthSnapshot)
            .where(
                IntegrationHealthSnapshot.tenant_id == principal.tenant_id,
                IntegrationHealthSnapshot.connection_id == connection.id,
            )
            .order_by(IntegrationHealthSnapshot.checked_at.desc(), IntegrationHealthSnapshot.id.desc())
            .limit(limit)
        )
    )
    return [_snapshot_out(value) for value in values]
