from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.lead_crm.api_schemas import (
    CRMConnectionCreate,
    CRMConnectionOut,
    CRMDeliveryOut,
    CRMMappingOut,
    CRMMappingPut,
    CRMRouteCreate,
    CRMRouteOut,
)
from northstar_api.lead_crm.audit import record_audit_event
from northstar_api.lead_crm.connectors import CRMCapabilities, CRMError, crm_registry
from northstar_api.lead_crm.credentials import CredentialStoreError, credential_store
from northstar_api.lead_crm.domain import CRMConnectionStatus
from northstar_api.lead_crm.models import CRMConnection, CRMDelivery, CRMRoute
from northstar_api.lead_crm.workspace_scope import WorkspaceCRMConnection, WorkspaceCRMRoute
from northstar_api.models import Lead
from northstar_api.routers import crm as legacy_crm
from northstar_api.security import Principal
from northstar_api.services.education_conversation_policy import education_source

router = APIRouter(tags=["crm"])
DB = Annotated[AsyncSession, Depends(get_session)]
CRMViewPrincipal = Annotated[Principal, Depends(require_permissions("crm.view"))]
CRMManagePrincipal = Annotated[Principal, Depends(require_permissions("crm.manage"))]


async def _scoped_connection(
    session: AsyncSession,
    principal: Principal,
    connection_id: UUID,
) -> CRMConnection | None:
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


async def _scoped_delivery(
    session: AsyncSession,
    principal: Principal,
    delivery_id: UUID,
) -> CRMDelivery | None:
    return await session.scalar(
        select(CRMDelivery)
        .join(Lead, Lead.id == CRMDelivery.lead_id)
        .where(
            CRMDelivery.id == delivery_id,
            CRMDelivery.tenant_id == principal.tenant_id,
            Lead.tenant_id == principal.tenant_id,
            Lead.workspace_id == principal.workspace_id,
        )
    )


@router.post("/crm/connections", response_model=CRMConnectionOut, status_code=201)
async def create_crm_connection(
    payload: CRMConnectionCreate,
    principal: CRMManagePrincipal,
    session: DB,
) -> CRMConnectionOut:
    duplicate = await session.scalar(
        select(CRMConnection.id)
        .join(WorkspaceCRMConnection, WorkspaceCRMConnection.connection_id == CRMConnection.id)
        .where(
            CRMConnection.tenant_id == principal.tenant_id,
            CRMConnection.name == payload.name,
            WorkspaceCRMConnection.workspace_id == principal.workspace_id,
        )
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="A CRM connection with that name already exists in this workspace")

    # The legacy table still has a tenant-wide unique name. Preserve compatibility
    # while allowing the same display name in different workspaces.
    stored_name = payload.name
    tenant_name_conflict = await session.scalar(
        select(CRMConnection.id).where(
            CRMConnection.tenant_id == principal.tenant_id,
            CRMConnection.name == stored_name,
        )
    )
    if tenant_name_conflict:
        stored_name = f"{payload.name} [{str(principal.workspace_id)[:8]}]"

    encrypted: bytes | None = None
    if payload.credentials:
        try:
            encrypted = credential_store.encrypt(payload.credentials)
        except CredentialStoreError as exc:
            raise HTTPException(status_code=503, detail="CRM credential encryption is not configured") from exc

    capabilities = CRMCapabilities()
    try:
        capabilities = crm_registry.get(payload.provider).capabilities
    except CRMError:
        pass

    connection = CRMConnection(
        tenant_id=principal.tenant_id,
        provider=payload.provider.value,
        name=stored_name,
        environment=payload.environment,
        region=payload.region,
        status=CRMConnectionStatus.CONNECTING.value if encrypted else CRMConnectionStatus.DRAFT.value,
        credentials_encrypted=encrypted,
        configuration_json=payload.configuration,
        capabilities_json={
            "oauth": capabilities.oauth,
            "schemaDiscovery": capabilities.schema_discovery,
            "create": capabilities.create,
            "update": capabilities.update,
            "upsert": capabilities.upsert,
            "readBack": capabilities.read_back,
            "inboundWebhooks": capabilities.inbound_webhooks,
            "webhookManagement": capabilities.webhook_management,
        },
    )
    session.add(connection)
    await session.flush()
    session.add(
        WorkspaceCRMConnection(
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            connection_id=connection.id,
            auto_sync_new_leads=True,
            auto_sync_updates=True,
        )
    )

    # Default all-leads route implements the product default: a connected CRM
    # receives every new Lead in its workspace unless the user later changes it.
    default_route = CRMRoute(
        tenant_id=principal.tenant_id,
        name=f"Auto sync {stored_name}",
        enabled=True,
        priority=100,
        conditions_json={},
        actions_json={"connectionIds": [str(connection.id)]},
    )
    session.add(default_route)
    await session.flush()
    session.add(
        WorkspaceCRMRoute(
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            route_id=default_route.id,
        )
    )
    record_audit_event(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id,
        action="crm.connection.created",
        entity_type="crm_connection",
        entity_id=str(connection.id),
        category="crm",
        after={
            "provider": connection.provider,
            "name": payload.name,
            "environment": connection.environment,
            "region": connection.region,
            "status": connection.status,
        },
        metadata={
            "defaultRouteId": str(default_route.id),
            "credentialsConfigured": encrypted is not None,
        },
    )
    await session.commit()
    await session.refresh(connection)
    return legacy_crm._connection_out(connection)


@router.get("/crm/connections", response_model=list[CRMConnectionOut])
async def list_crm_connections(
    principal: CRMViewPrincipal,
    session: DB,
) -> list[CRMConnectionOut]:
    values = list(
        await session.scalars(
            select(CRMConnection)
            .join(WorkspaceCRMConnection, WorkspaceCRMConnection.connection_id == CRMConnection.id)
            .where(
                CRMConnection.tenant_id == principal.tenant_id,
                WorkspaceCRMConnection.tenant_id == principal.tenant_id,
                WorkspaceCRMConnection.workspace_id == principal.workspace_id,
            )
            .order_by(CRMConnection.created_at.desc())
        )
    )
    return [legacy_crm._connection_out(value) for value in values]


@router.get("/crm/connections/{connection_id}", response_model=CRMConnectionOut)
async def get_crm_connection(
    connection_id: UUID,
    principal: CRMViewPrincipal,
    session: DB,
) -> CRMConnectionOut:
    value = await _scoped_connection(session, principal, connection_id)
    if not value:
        raise HTTPException(status_code=404, detail="CRM connection not found in this workspace")
    return legacy_crm._connection_out(value)


@router.delete("/crm/connections/{connection_id}", status_code=204)
async def delete_crm_connection(
    connection_id: UUID,
    principal: CRMManagePrincipal,
    session: DB,
) -> None:
    value = await _scoped_connection(session, principal, connection_id)
    if not value:
        raise HTTPException(status_code=404, detail="CRM connection not found in this workspace")
    before = {
        "status": value.status,
        "credentialsConfigured": bool(value.credentials_encrypted or value.credentials_ref),
    }
    value.status = CRMConnectionStatus.DISABLED.value
    value.credentials_encrypted = None
    value.credentials_ref = None
    record_audit_event(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id,
        action="crm.connection.disabled",
        entity_type="crm_connection",
        entity_id=str(value.id),
        category="crm",
        severity="warning",
        before=before,
        after={"status": value.status, "credentialsConfigured": False},
    )
    await session.commit()


@router.post("/crm/connections/{connection_id}/test")
async def test_crm_connection(
    connection_id: UUID,
    principal: CRMManagePrincipal,
    session: DB,
) -> dict[str, Any]:
    if not await _scoped_connection(session, principal, connection_id):
        raise HTTPException(status_code=404, detail="CRM connection not found in this workspace")
    return await legacy_crm.test_crm_connection(connection_id, principal, session)


@router.get("/crm/connections/{connection_id}/health")
async def crm_connection_health(
    connection_id: UUID,
    principal: CRMViewPrincipal,
    session: DB,
) -> dict[str, Any]:
    if not await _scoped_connection(session, principal, connection_id):
        raise HTTPException(status_code=404, detail="CRM connection not found in this workspace")
    return await legacy_crm.crm_connection_health(connection_id, principal, session)


@router.put("/crm/connections/{connection_id}/mappings", response_model=CRMMappingOut)
async def put_crm_mapping(
    connection_id: UUID,
    payload: CRMMappingPut,
    principal: CRMManagePrincipal,
    session: DB,
) -> CRMMappingOut:
    if not await _scoped_connection(session, principal, connection_id):
        raise HTTPException(status_code=404, detail="CRM connection not found in this workspace")
    record_audit_event(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id,
        action="crm.mapping.updated",
        entity_type="crm_mapping",
        entity_id=f"{connection_id}:{payload.object_name}",
        category="crm",
        after={"objectName": payload.object_name, "mapping": payload.mapping},
        metadata={"connectionId": str(connection_id)},
    )
    return await legacy_crm.put_crm_mapping(connection_id, payload, principal, session)


@router.get("/crm/connections/{connection_id}/mappings", response_model=list[CRMMappingOut])
async def list_crm_mappings(
    connection_id: UUID,
    principal: CRMViewPrincipal,
    session: DB,
) -> list[CRMMappingOut]:
    if not await _scoped_connection(session, principal, connection_id):
        raise HTTPException(status_code=404, detail="CRM connection not found in this workspace")
    return await legacy_crm.list_crm_mappings(connection_id, principal, session)


@router.post("/crm/routes", response_model=CRMRouteOut, status_code=201)
async def create_crm_route(
    payload: CRMRouteCreate,
    principal: CRMManagePrincipal,
    session: DB,
) -> CRMRouteOut:
    if payload.connection_ids:
        owned = set(
            await session.scalars(
                select(CRMConnection.id)
                .join(WorkspaceCRMConnection, WorkspaceCRMConnection.connection_id == CRMConnection.id)
                .where(
                    CRMConnection.tenant_id == principal.tenant_id,
                    CRMConnection.id.in_(payload.connection_ids),
                    WorkspaceCRMConnection.workspace_id == principal.workspace_id,
                )
            )
        )
        if owned != set(payload.connection_ids):
            raise HTTPException(status_code=400, detail="Route references a CRM connection outside this workspace")

    route_name = payload.name
    tenant_conflict = await session.scalar(
        select(CRMRoute.id).where(CRMRoute.tenant_id == principal.tenant_id, CRMRoute.name == route_name)
    )
    if tenant_conflict:
        route_name = f"{payload.name} [{str(principal.workspace_id)[:8]}]"

    value = CRMRoute(
        tenant_id=principal.tenant_id,
        name=route_name,
        enabled=payload.enabled,
        priority=payload.priority,
        conditions_json=payload.conditions,
        actions_json={"connectionIds": [str(item) for item in payload.connection_ids]},
    )
    session.add(value)
    await session.flush()
    session.add(
        WorkspaceCRMRoute(
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            route_id=value.id,
        )
    )
    record_audit_event(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id,
        action="crm.route.created",
        entity_type="crm_route",
        entity_id=str(value.id),
        category="crm",
        after={
            "name": payload.name,
            "enabled": value.enabled,
            "priority": value.priority,
            "conditions": value.conditions_json,
            "connectionIds": value.actions_json.get("connectionIds", []),
        },
    )
    await session.commit()
    await session.refresh(value)
    return CRMRouteOut(
        id=value.id,
        name=payload.name,
        enabled=value.enabled,
        priority=value.priority,
        version=value.version,
        conditions=value.conditions_json,
        connection_ids=value.actions_json.get("connectionIds", []),
        created_at=value.created_at,
        updated_at=value.updated_at,
    )


@router.get("/crm/routes", response_model=list[CRMRouteOut])
async def list_crm_routes(
    principal: CRMViewPrincipal,
    session: DB,
) -> list[CRMRouteOut]:
    values = list(
        await session.scalars(
            select(CRMRoute)
            .join(WorkspaceCRMRoute, WorkspaceCRMRoute.route_id == CRMRoute.id)
            .where(
                CRMRoute.tenant_id == principal.tenant_id,
                WorkspaceCRMRoute.tenant_id == principal.tenant_id,
                WorkspaceCRMRoute.workspace_id == principal.workspace_id,
            )
            .order_by(CRMRoute.priority, CRMRoute.created_at)
        )
    )
    return [
        CRMRouteOut(
            id=value.id,
            name=value.name,
            enabled=value.enabled,
            priority=value.priority,
            version=value.version,
            conditions=value.conditions_json,
            connection_ids=value.actions_json.get("connectionIds", []),
            created_at=value.created_at,
            updated_at=value.updated_at,
        )
        for value in values
    ]


@router.get("/crm/deliveries", response_model=list[CRMDeliveryOut])
async def list_crm_deliveries(
    principal: CRMViewPrincipal,
    session: DB,
) -> list[CRMDeliveryOut]:
    values = list(
        await session.scalars(
            select(CRMDelivery)
            .join(Lead, Lead.id == CRMDelivery.lead_id)
            .where(
                CRMDelivery.tenant_id == principal.tenant_id,
                Lead.tenant_id == principal.tenant_id,
                Lead.workspace_id == principal.workspace_id,
                ~education_source(Lead),
            )
            .order_by(CRMDelivery.created_at.desc())
            .limit(500)
        )
    )
    return [legacy_crm._delivery_out(value) for value in values]


@router.post("/crm/deliveries/{delivery_id}/retry", response_model=CRMDeliveryOut)
async def retry_crm_delivery(
    delivery_id: UUID,
    principal: CRMManagePrincipal,
    session: DB,
) -> CRMDeliveryOut:
    delivery = await _scoped_delivery(session, principal, delivery_id)
    if not delivery:
        raise HTTPException(status_code=404, detail="CRM delivery not found in this workspace")
    verification_retry = delivery.acknowledged_at is not None
    record_audit_event(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id,
        action="crm.delivery.retry_requested",
        entity_type="crm_delivery",
        entity_id=str(delivery.id),
        category="crm",
        severity="warning",
        before={
            "status": delivery.status,
            "verificationStatus": delivery.verification_status,
        },
        after={
            "status": "acknowledged" if verification_retry else "retrying",
            "verificationStatus": "pending" if verification_retry else delivery.verification_status,
        },
        metadata={
            "phase": "verification" if verification_retry else "delivery",
            "leadId": str(delivery.lead_id),
            "connectionId": str(delivery.connection_id),
        },
    )
    return await legacy_crm.retry_crm_delivery(delivery_id, principal, session)


@router.post("/crm/deliveries/{delivery_id}/cancel", response_model=CRMDeliveryOut)
async def cancel_crm_delivery(
    delivery_id: UUID,
    principal: CRMManagePrincipal,
    session: DB,
) -> CRMDeliveryOut:
    delivery = await _scoped_delivery(session, principal, delivery_id)
    if not delivery:
        raise HTTPException(status_code=404, detail="CRM delivery not found in this workspace")
    record_audit_event(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id,
        action="crm.delivery.cancelled",
        entity_type="crm_delivery",
        entity_id=str(delivery.id),
        category="crm",
        severity="warning",
        before={"status": delivery.status},
        after={"status": "cancelled"},
        metadata={
            "leadId": str(delivery.lead_id),
            "connectionId": str(delivery.connection_id),
        },
    )
    return await legacy_crm.cancel_crm_delivery(delivery_id, principal, session)
