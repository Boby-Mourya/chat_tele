from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.lead_crm.api_schemas import CRMRouteOut
from northstar_api.lead_crm.audit import record_audit_event
from northstar_api.lead_crm.models import CRMConnection, CRMRoute
from northstar_api.lead_crm.workspace_scope import WorkspaceCRMConnection, WorkspaceCRMRoute
from northstar_api.security import Principal

router = APIRouter(tags=["crm"])
DB = Annotated[AsyncSession, Depends(get_session)]
CRMManagePrincipal = Annotated[Principal, Depends(require_permissions("crm.manage"))]


class CRMRoutePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=2, max_length=160)
    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=10000)
    conditions: dict[str, Any] | None = None
    connection_ids: list[UUID] | None = None


def _route_out(value: CRMRoute) -> CRMRouteOut:
    actions = dict(value.actions_json or {})
    raw_connection_ids = actions.get("connectionIds")
    connection_ids = [str(item) for item in raw_connection_ids] if isinstance(raw_connection_ids, list) else []
    return CRMRouteOut(
        id=value.id,
        name=value.name,
        enabled=value.enabled,
        priority=value.priority,
        version=value.version,
        conditions=dict(value.conditions_json or {}),
        connection_ids=connection_ids,
        created_at=value.created_at,
        updated_at=value.updated_at,
    )


def _route_snapshot(value: CRMRoute) -> dict[str, Any]:
    actions = dict(value.actions_json or {})
    raw_connection_ids = actions.get("connectionIds")
    return {
        "name": value.name,
        "enabled": value.enabled,
        "priority": value.priority,
        "version": value.version,
        "conditions": dict(value.conditions_json or {}),
        "connectionIds": [str(item) for item in raw_connection_ids]
        if isinstance(raw_connection_ids, list)
        else [],
    }


async def _assert_connections_owned(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    connection_ids: list[UUID],
) -> None:
    if not connection_ids:
        return
    owned = set(
        await session.scalars(
            select(CRMConnection.id)
            .join(WorkspaceCRMConnection, WorkspaceCRMConnection.connection_id == CRMConnection.id)
            .where(
                CRMConnection.tenant_id == tenant_id,
                CRMConnection.id.in_(connection_ids),
                WorkspaceCRMConnection.tenant_id == tenant_id,
                WorkspaceCRMConnection.workspace_id == workspace_id,
            )
        )
    )
    if owned != set(connection_ids):
        raise HTTPException(status_code=400, detail="Route references a CRM connection outside this workspace")


async def _route(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    route_id: UUID,
) -> CRMRoute | None:
    return await session.scalar(
        select(CRMRoute)
        .join(WorkspaceCRMRoute, WorkspaceCRMRoute.route_id == CRMRoute.id)
        .where(
            CRMRoute.id == route_id,
            CRMRoute.tenant_id == tenant_id,
            WorkspaceCRMRoute.tenant_id == tenant_id,
            WorkspaceCRMRoute.workspace_id == workspace_id,
        )
    )


@router.patch("/crm/routes/{route_id}", response_model=CRMRouteOut)
async def patch_crm_route(
    route_id: UUID,
    payload: CRMRoutePatch,
    principal: CRMManagePrincipal,
    session: DB,
) -> CRMRouteOut:
    value = await _route(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        route_id=route_id,
    )
    if value is None:
        raise HTTPException(status_code=404, detail="CRM route not found in this workspace")
    before = _route_snapshot(value)
    if payload.connection_ids is not None:
        await _assert_connections_owned(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            connection_ids=payload.connection_ids,
        )
        value.actions_json = {"connectionIds": [str(item) for item in payload.connection_ids]}
    if payload.name is not None:
        value.name = payload.name
    if payload.enabled is not None:
        value.enabled = payload.enabled
    if payload.priority is not None:
        value.priority = payload.priority
    if payload.conditions is not None:
        value.conditions_json = payload.conditions
    value.version += 1
    record_audit_event(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id,
        action="crm.route.updated",
        entity_type="crm_route",
        entity_id=str(value.id),
        category="crm",
        before=before,
        after=_route_snapshot(value),
    )
    await session.commit()
    await session.refresh(value)
    return _route_out(value)


@router.delete("/crm/routes/{route_id}", status_code=204)
async def delete_crm_route(
    route_id: UUID,
    principal: CRMManagePrincipal,
    session: DB,
) -> None:
    value = await _route(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        route_id=route_id,
    )
    if value is None:
        raise HTTPException(status_code=404, detail="CRM route not found in this workspace")
    before = _route_snapshot(value)
    record_audit_event(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id,
        action="crm.route.deleted",
        entity_type="crm_route",
        entity_id=str(value.id),
        category="crm",
        severity="warning",
        before=before,
        after={"deleted": True},
    )
    await session.delete(value)
    await session.commit()
