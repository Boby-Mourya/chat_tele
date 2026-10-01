from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from northstar_api.database import get_session
from northstar_api.dependencies import AdminPrincipal, require_permissions
from northstar_api.lead_crm.audit import redact_audit_payload
from northstar_api.lead_crm.audit_models import IntegrationAuditEvent
from northstar_api.models import Role
from northstar_api.schemas import APIModel
from northstar_api.security import Principal

# Keep the historical endpoint and response shape for existing integration tooling.
router = APIRouter(prefix="/integration-audit", tags=["integration-audit"])
audit_router = APIRouter(prefix="/audit", tags=["audit"])
DB = Annotated[AsyncSession, Depends(get_session)]
AuditViewPrincipal = Annotated[Principal, Depends(require_permissions("audit.view"))]
AuditCategory = Literal[
    "security",
    "workspace",
    "access",
    "agent",
    "conversation",
    "education",
    "lead",
    "crm",
    "channel",
    "billing",
    "api",
    "integration",
    "system",
]
AuditSeverity = Literal["info", "warning", "critical"]
AuditOutcome = Literal["success", "denied", "failure"]
_TENANT_AUDIT_ROLES = frozenset({Role.OWNER, Role.ADMIN, Role.SECURITY_ADMIN})


class IntegrationAuditOut(BaseModel):
    id: UUID
    actor_user_id: UUID | None
    action: str
    entity_type: str
    entity_id: str
    before: dict[str, Any]
    after: dict[str, Any]
    request_id: str | None
    ip_address: str | None
    user_agent: str | None
    created_at: datetime


class AuditEventOut(APIModel):
    id: UUID
    tenant_id: UUID
    workspace_id: UUID | None
    actor_user_id: UUID | None
    action: str
    entity_type: str
    entity_id: str
    category: str
    severity: str
    outcome: str
    before: dict[str, Any]
    after: dict[str, Any]
    metadata: dict[str, Any]
    request_id: str | None
    ip_address: str | None
    user_agent: str | None
    created_at: datetime


def _legacy_out(value: IntegrationAuditEvent) -> IntegrationAuditOut:
    return IntegrationAuditOut(
        id=value.id,
        actor_user_id=value.actor_user_id,
        action=value.action,
        entity_type=value.entity_type,
        entity_id=value.entity_id,
        before=redact_audit_payload(value.before_json),
        after=redact_audit_payload(value.after_json),
        request_id=value.request_id,
        ip_address=value.ip_address,
        user_agent=value.user_agent,
        created_at=value.created_at,
    )


def _audit_out(value: IntegrationAuditEvent) -> AuditEventOut:
    return AuditEventOut(
        id=value.id,
        tenant_id=value.tenant_id,
        workspace_id=value.workspace_id,
        actor_user_id=value.actor_user_id,
        action=value.action,
        entity_type=value.entity_type,
        entity_id=value.entity_id,
        category=value.category,
        severity=value.severity,
        outcome=value.outcome,
        before=redact_audit_payload(value.before_json),
        after=redact_audit_payload(value.after_json),
        metadata=redact_audit_payload(value.metadata_json),
        request_id=value.request_id,
        ip_address=value.ip_address,
        user_agent=value.user_agent,
        created_at=value.created_at,
    )


@router.get("", response_model=list[IntegrationAuditOut])
async def list_integration_audit(
    principal: AdminPrincipal,
    session: DB,
    entity_type: str | None = Query(default=None, max_length=100),
    entity_id: str | None = Query(default=None, max_length=160),
    action: str | None = Query(default=None, max_length=160),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[IntegrationAuditOut]:
    query = select(IntegrationAuditEvent).where(IntegrationAuditEvent.tenant_id == principal.tenant_id)
    if entity_type:
        query = query.where(IntegrationAuditEvent.entity_type == entity_type)
    if entity_id:
        query = query.where(IntegrationAuditEvent.entity_id == entity_id)
    if action:
        query = query.where(IntegrationAuditEvent.action == action)
    values = list(
        await session.scalars(query.order_by(IntegrationAuditEvent.created_at.desc()).limit(limit))
    )
    return [_legacy_out(value) for value in values]


def _scoped_query(
    principal: Principal,
    *,
    category: AuditCategory | None,
    severity: AuditSeverity | None,
    outcome: AuditOutcome | None,
    action: str | None,
    entity_type: str | None,
    actor_user_id: UUID | None,
    from_time: datetime | None,
    to_time: datetime | None,
    search: str | None,
) -> Select[tuple[IntegrationAuditEvent]]:
    query = select(IntegrationAuditEvent).where(IntegrationAuditEvent.tenant_id == principal.tenant_id)
    if principal.workspace_id is not None:
        workspace_clause = IntegrationAuditEvent.workspace_id == principal.workspace_id
        # Legacy/tenant-wide rows have no workspace_id. Only tenant security roles
        # may inspect those rows; a workspace-only admin remains strictly scoped.
        if principal.role in _TENANT_AUDIT_ROLES:
            workspace_clause = or_(workspace_clause, IntegrationAuditEvent.workspace_id.is_(None))
        query = query.where(workspace_clause)
    if category:
        query = query.where(IntegrationAuditEvent.category == category)
    if severity:
        query = query.where(IntegrationAuditEvent.severity == severity)
    if outcome:
        query = query.where(IntegrationAuditEvent.outcome == outcome)
    if action:
        query = query.where(IntegrationAuditEvent.action == action)
    if entity_type:
        query = query.where(IntegrationAuditEvent.entity_type == entity_type)
    if actor_user_id:
        query = query.where(IntegrationAuditEvent.actor_user_id == actor_user_id)
    if from_time:
        query = query.where(IntegrationAuditEvent.created_at >= from_time)
    if to_time:
        query = query.where(IntegrationAuditEvent.created_at <= to_time)
    if search:
        pattern = f"%{search.strip()}%"
        query = query.where(
            or_(
                IntegrationAuditEvent.action.ilike(pattern),
                IntegrationAuditEvent.entity_type.ilike(pattern),
                IntegrationAuditEvent.entity_id.ilike(pattern),
                IntegrationAuditEvent.request_id.ilike(pattern),
            )
        )
    return query


async def _audit_values(
    principal: Principal,
    session: AsyncSession,
    *,
    category: AuditCategory | None = None,
    severity: AuditSeverity | None = None,
    outcome: AuditOutcome | None = None,
    action: str | None = None,
    entity_type: str | None = None,
    actor_user_id: UUID | None = None,
    from_time: datetime | None = None,
    to_time: datetime | None = None,
    search: str | None = None,
    limit: int = 100,
) -> list[IntegrationAuditEvent]:
    query = _scoped_query(
        principal,
        category=category,
        severity=severity,
        outcome=outcome,
        action=action,
        entity_type=entity_type,
        actor_user_id=actor_user_id,
        from_time=from_time,
        to_time=to_time,
        search=search,
    )
    return list(
        await session.scalars(query.order_by(IntegrationAuditEvent.created_at.desc()).limit(limit))
    )


@audit_router.get("", response_model=list[AuditEventOut])
@audit_router.get("/events", response_model=list[AuditEventOut])
async def list_audit_events(
    principal: AuditViewPrincipal,
    session: DB,
    category: AuditCategory | None = Query(default=None),
    severity: AuditSeverity | None = Query(default=None),
    outcome: AuditOutcome | None = Query(default=None),
    action: str | None = Query(default=None, max_length=160),
    entity_type: str | None = Query(default=None, max_length=100),
    actor_user_id: UUID | None = Query(default=None),
    from_time: datetime | None = Query(default=None, alias="from"),
    to_time: datetime | None = Query(default=None, alias="to"),
    search: str | None = Query(default=None, min_length=1, max_length=160),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[AuditEventOut]:
    values = await _audit_values(
        principal,
        session,
        category=category,
        severity=severity,
        outcome=outcome,
        action=action,
        entity_type=entity_type,
        actor_user_id=actor_user_id,
        from_time=from_time,
        to_time=to_time,
        search=search,
        limit=limit,
    )
    return [_audit_out(value) for value in values]


def _csv_cell(value: object | None) -> str:
    text = "" if value is None else str(value)
    if text.startswith(("=", "+", "-", "@", "\t", "\r", "\n")):
        return "'" + text
    return text


@audit_router.get("/export")
async def export_audit_events(
    principal: AuditViewPrincipal,
    session: DB,
    category: AuditCategory | None = Query(default=None),
    severity: AuditSeverity | None = Query(default=None),
    outcome: AuditOutcome | None = Query(default=None),
    action: str | None = Query(default=None, max_length=160),
    entity_type: str | None = Query(default=None, max_length=100),
    actor_user_id: UUID | None = Query(default=None),
    from_time: datetime | None = Query(default=None, alias="from"),
    to_time: datetime | None = Query(default=None, alias="to"),
    search: str | None = Query(default=None, min_length=1, max_length=160),
    limit: int = Query(default=500, ge=1, le=5000),
) -> Response:
    values = await _audit_values(
        principal,
        session,
        category=category,
        severity=severity,
        outcome=outcome,
        action=action,
        entity_type=entity_type,
        actor_user_id=actor_user_id,
        from_time=from_time,
        to_time=to_time,
        search=search,
        limit=limit,
    )
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(
        [
            "created_at",
            "workspace_id",
            "actor_user_id",
            "category",
            "severity",
            "outcome",
            "action",
            "entity_type",
            "entity_id",
            "request_id",
            "ip_address",
        ]
    )
    for value in values:
        writer.writerow(
            [
                _csv_cell(value.created_at.isoformat()),
                _csv_cell(value.workspace_id),
                _csv_cell(value.actor_user_id),
                _csv_cell(value.category),
                _csv_cell(value.severity),
                _csv_cell(value.outcome),
                _csv_cell(value.action),
                _csv_cell(value.entity_type),
                _csv_cell(value.entity_id),
                _csv_cell(value.request_id),
                _csv_cell(value.ip_address),
            ]
        )
    return Response(
        content=stream.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="northstar-audit.csv"'},
    )
