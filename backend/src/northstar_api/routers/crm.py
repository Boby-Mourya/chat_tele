from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import get_session
from northstar_api.dependencies import AdminPrincipal, CurrentPrincipal, WorkspaceWritePrincipal
from northstar_api.lead_crm.api_schemas import (
    CRMConnectionCreate,
    CRMConnectionOut,
    CRMDeliveryOut,
    CRMMappingOut,
    CRMMappingPut,
    CRMRouteCreate,
    CRMRouteOut,
    LeadActivityOut,
    QualifyLeadRequest,
    SyncLeadRequest,
)
from northstar_api.lead_crm.connectors import CRMCapabilities, CRMError, crm_registry
from northstar_api.lead_crm.credentials import CredentialStoreError, credential_store
from northstar_api.lead_crm.domain import CRMConnectionStatus, CRMDeliveryStatus, CRMProvider
from northstar_api.lead_crm.models import (
    CRMConnection,
    CRMDelivery,
    CRMFieldMapping,
    CRMRoute,
    LeadActivityEvent,
)
from northstar_api.lead_crm.services import lead_domain_service
from northstar_api.logging import request_id_ctx
from northstar_api.models import Lead
from northstar_api.services.education_conversation_policy import education_source

router = APIRouter(tags=["crm"])
DB = Annotated[AsyncSession, Depends(get_session)]


def _connection_out(value: CRMConnection) -> CRMConnectionOut:
    return CRMConnectionOut(
        id=value.id,
        public_id=value.public_id,
        provider=value.provider,
        name=value.name,
        environment=value.environment,
        region=value.region,
        status=value.status,
        configuration=value.configuration_json,
        capabilities=value.capabilities_json,
        last_authenticated_at=value.last_authenticated_at,
        last_health_at=value.last_health_at,
        last_success_at=value.last_success_at,
        last_failure_at=value.last_failure_at,
        last_error=value.last_error,
        created_at=value.created_at,
        updated_at=value.updated_at,
    )


def _delivery_out(value: CRMDelivery) -> CRMDeliveryOut:
    return CRMDeliveryOut(
        id=value.id,
        lead_id=value.lead_id,
        connection_id=value.connection_id,
        provider=value.provider,
        operation=value.operation,
        status=CRMDeliveryStatus(value.status),
        attempt_count=value.attempt_count,
        verification_status=value.verification_status,
        verification_attempt_count=value.verification_attempt_count,
        next_verification_at=value.next_verification_at,
        verification_error_code=value.verification_error_code,
        verification_error_message=value.verification_error_message,
        verification_evidence=value.verification_evidence_json,
        external_record_id=value.external_record_id,
        queued_at=value.queued_at,
        sent_at=value.sent_at,
        acknowledged_at=value.acknowledged_at,
        verified_at=value.verified_at,
        next_retry_at=value.next_retry_at,
        last_error_code=value.last_error_code,
        last_error_message=value.last_error_message,
        provider_http_status=value.provider_http_status,
        provider_code=value.provider_code,
        provider_request_id=value.provider_request_id,
        created_at=value.created_at,
        updated_at=value.updated_at,
    )


@router.get("/crm/providers")
async def crm_providers(_: CurrentPrincipal) -> list[dict[str, Any]]:
    registered = set(crm_registry.providers())
    return [
        {
            "id": provider.value,
            "name": provider.value.replace("_", " ").title(),
            "native": provider not in {CRMProvider.GENERIC_REST, CRMProvider.GENERIC_WEBHOOK},
            "runtimeRegistered": provider in registered,
        }
        for provider in CRMProvider
    ]


@router.post("/crm/connections", response_model=CRMConnectionOut, status_code=201)
async def create_crm_connection(
    payload: CRMConnectionCreate,
    principal: AdminPrincipal,
    session: DB,
) -> CRMConnectionOut:
    duplicate = await session.scalar(
        select(CRMConnection.id).where(
            CRMConnection.tenant_id == principal.tenant_id,
            CRMConnection.name == payload.name,
        )
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="A CRM connection with that name already exists")
    encrypted: bytes | None = None
    if payload.credentials:
        try:
            encrypted = credential_store.encrypt(payload.credentials)
        except CredentialStoreError as exc:
            raise HTTPException(
                status_code=503, detail="CRM credential encryption is not configured"
            ) from exc
    capabilities = CRMCapabilities()
    try:
        connector = crm_registry.get(payload.provider)
        capabilities = connector.capabilities
    except CRMError:
        capabilities = CRMCapabilities()
    connection = CRMConnection(
        tenant_id=principal.tenant_id,
        public_id=f"crm_{UUID(int=UUID(bytes=__import__('os').urandom(16)).int).hex}",
        provider=payload.provider.value,
        name=payload.name,
        environment=payload.environment,
        region=payload.region,
        status=(CRMConnectionStatus.CONNECTING.value if encrypted else CRMConnectionStatus.DRAFT.value),
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
    await session.commit()
    await session.refresh(connection)
    return _connection_out(connection)


@router.get("/crm/connections", response_model=list[CRMConnectionOut])
async def list_crm_connections(principal: CurrentPrincipal, session: DB) -> list[CRMConnectionOut]:
    values = list(
        await session.scalars(
            select(CRMConnection)
            .where(CRMConnection.tenant_id == principal.tenant_id)
            .order_by(CRMConnection.created_at.desc())
        )
    )
    return [_connection_out(value) for value in values]


@router.get("/crm/connections/{connection_id}", response_model=CRMConnectionOut)
async def get_crm_connection(
    connection_id: UUID, principal: CurrentPrincipal, session: DB
) -> CRMConnectionOut:
    value = await session.scalar(
        select(CRMConnection).where(
            CRMConnection.id == connection_id,
            CRMConnection.tenant_id == principal.tenant_id,
        )
    )
    if not value:
        raise HTTPException(status_code=404, detail="CRM connection not found")
    return _connection_out(value)


@router.delete("/crm/connections/{connection_id}", status_code=204)
async def delete_crm_connection(connection_id: UUID, principal: AdminPrincipal, session: DB) -> None:
    value = await session.scalar(
        select(CRMConnection).where(
            CRMConnection.id == connection_id,
            CRMConnection.tenant_id == principal.tenant_id,
        )
    )
    if not value:
        raise HTTPException(status_code=404, detail="CRM connection not found")
    value.status = CRMConnectionStatus.DISABLED.value
    value.credentials_encrypted = None
    value.credentials_ref = None
    await session.commit()


@router.post("/crm/connections/{connection_id}/test")
async def test_crm_connection(connection_id: UUID, principal: AdminPrincipal, session: DB) -> dict[str, Any]:
    connection = await session.scalar(
        select(CRMConnection).where(
            CRMConnection.id == connection_id,
            CRMConnection.tenant_id == principal.tenant_id,
        )
    )
    if not connection:
        raise HTTPException(status_code=404, detail="CRM connection not found")
    try:
        connector = crm_registry.get(CRMProvider(connection.provider))
    except Exception as exc:
        connection.status = CRMConnectionStatus.CONFIGURATION_ERROR.value
        connection.last_error = "Connector runtime is not registered"
        connection.last_health_at = datetime.now(UTC)
        await session.commit()
        raise HTTPException(status_code=409, detail="CRM connector is not available in this runtime") from exc
    credentials: dict[str, Any] = {}
    if connection.credentials_encrypted:
        try:
            credentials = credential_store.decrypt(connection.credentials_encrypted)
        except CredentialStoreError as exc:
            connection.status = CRMConnectionStatus.AUTH_REQUIRED.value
            connection.last_error = "Stored credentials could not be decrypted"
            connection.last_health_at = datetime.now(UTC)
            await session.commit()
            raise HTTPException(status_code=409, detail="CRM credentials require reconnection") from exc
    from northstar_api.lead_crm.connectors import CRMConnectionContext

    result = await connector.health_check(
        CRMConnectionContext(
            tenant_id=principal.tenant_id,
            connection_id=connection.id,
            provider=CRMProvider(connection.provider),
            configuration=connection.configuration_json,
            credentials=credentials,
        )
    )
    connection.last_health_at = datetime.now(UTC)
    connection.status = result.status.value
    connection.last_error = (
        None
        if result.status.value == "healthy"
        else str(result.details.get("error", "Health check failed"))[:1000]
    )
    await session.commit()
    return {
        "status": result.status.value,
        "checks": result.checks,
        "latencyMs": result.latency_ms,
        "details": result.details,
    }


@router.get("/crm/connections/{connection_id}/health")
async def crm_connection_health(
    connection_id: UUID, principal: CurrentPrincipal, session: DB
) -> dict[str, Any]:
    connection = await session.scalar(
        select(CRMConnection).where(
            CRMConnection.id == connection_id,
            CRMConnection.tenant_id == principal.tenant_id,
        )
    )
    if not connection:
        raise HTTPException(status_code=404, detail="CRM connection not found")
    queued = len(
        list(
            await session.scalars(
                select(CRMDelivery.id).where(
                    CRMDelivery.tenant_id == principal.tenant_id,
                    CRMDelivery.connection_id == connection.id,
                    CRMDelivery.status.in_(("queued", "retrying", "rate_limited")),
                )
            )
        )
    )
    return {
        "connectionId": str(connection.id),
        "provider": connection.provider,
        "status": connection.status,
        "checks": {
            "credentials": "configured"
            if connection.credentials_encrypted or connection.credentials_ref
            else "missing",
            "api": "unknown" if connection.last_health_at is None else connection.status,
            "schema": "unknown",
            "mapping": "unknown",
            "webhook": "unknown",
            "delivery": "queued" if queued else "idle",
        },
        "queue": {"pending": queued},
        "lastHealthAt": connection.last_health_at,
        "lastSuccessAt": connection.last_success_at,
        "lastFailureAt": connection.last_failure_at,
        "lastError": connection.last_error,
    }


@router.put("/crm/connections/{connection_id}/mappings", response_model=CRMMappingOut)
async def put_crm_mapping(
    connection_id: UUID,
    payload: CRMMappingPut,
    principal: AdminPrincipal,
    session: DB,
) -> CRMMappingOut:
    connection = await session.scalar(
        select(CRMConnection).where(
            CRMConnection.id == connection_id,
            CRMConnection.tenant_id == principal.tenant_id,
        )
    )
    if not connection:
        raise HTTPException(status_code=404, detail="CRM connection not found")
    value = await session.scalar(
        select(CRMFieldMapping).where(
            CRMFieldMapping.tenant_id == principal.tenant_id,
            CRMFieldMapping.connection_id == connection_id,
            CRMFieldMapping.object_name == payload.object_name,
        )
    )
    if value is None:
        value = CRMFieldMapping(
            tenant_id=principal.tenant_id,
            connection_id=connection_id,
            object_name=payload.object_name,
            mapping_json=payload.mapping,
            status="draft",
        )
        session.add(value)
    else:
        value.version += 1
        value.mapping_json = payload.mapping
        value.status = "draft"
        value.validation_json = {}
    await session.commit()
    return CRMMappingOut(
        connection_id=value.connection_id,
        object_name=value.object_name,
        version=value.version,
        status=value.status,
        mapping=value.mapping_json,
        validation=value.validation_json,
        schema_hash=value.schema_hash,
    )


@router.get("/crm/connections/{connection_id}/mappings", response_model=list[CRMMappingOut])
async def list_crm_mappings(
    connection_id: UUID, principal: CurrentPrincipal, session: DB
) -> list[CRMMappingOut]:
    connection = await session.scalar(
        select(CRMConnection.id).where(
            CRMConnection.id == connection_id,
            CRMConnection.tenant_id == principal.tenant_id,
        )
    )
    if not connection:
        raise HTTPException(status_code=404, detail="CRM connection not found")
    values = list(
        await session.scalars(
            select(CRMFieldMapping).where(
                CRMFieldMapping.tenant_id == principal.tenant_id,
                CRMFieldMapping.connection_id == connection_id,
            )
        )
    )
    return [
        CRMMappingOut(
            connection_id=value.connection_id,
            object_name=value.object_name,
            version=value.version,
            status=value.status,
            mapping=value.mapping_json,
            validation=value.validation_json,
            schema_hash=value.schema_hash,
        )
        for value in values
    ]


@router.post("/crm/routes", response_model=CRMRouteOut, status_code=201)
async def create_crm_route(payload: CRMRouteCreate, principal: AdminPrincipal, session: DB) -> CRMRouteOut:
    connection_ids = [str(item) for item in payload.connection_ids]
    owned = list(
        await session.scalars(
            select(CRMConnection.id).where(
                CRMConnection.tenant_id == principal.tenant_id,
                CRMConnection.id.in_(payload.connection_ids),
            )
        )
    )
    if len(set(owned)) != len(set(payload.connection_ids)):
        raise HTTPException(
            status_code=400, detail="Route references a CRM connection outside this workspace"
        )
    value = CRMRoute(
        tenant_id=principal.tenant_id,
        name=payload.name,
        enabled=payload.enabled,
        priority=payload.priority,
        conditions_json=payload.conditions,
        actions_json={"connectionIds": connection_ids},
    )
    session.add(value)
    await session.commit()
    await session.refresh(value)
    return CRMRouteOut(
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


@router.get("/crm/routes", response_model=list[CRMRouteOut])
async def list_crm_routes(principal: CurrentPrincipal, session: DB) -> list[CRMRouteOut]:
    values = list(
        await session.scalars(
            select(CRMRoute).where(CRMRoute.tenant_id == principal.tenant_id).order_by(CRMRoute.priority)
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
async def list_crm_deliveries(principal: CurrentPrincipal, session: DB) -> list[CRMDeliveryOut]:
    values = list(
        await session.scalars(
            select(CRMDelivery)
            .where(CRMDelivery.tenant_id == principal.tenant_id)
            .order_by(CRMDelivery.created_at.desc())
            .limit(500)
        )
    )
    return [_delivery_out(value) for value in values]


@router.post("/crm/deliveries/{delivery_id}/retry", response_model=CRMDeliveryOut)
async def retry_crm_delivery(delivery_id: UUID, principal: AdminPrincipal, session: DB) -> CRMDeliveryOut:
    value = await session.scalar(
        select(CRMDelivery)
        .where(CRMDelivery.id == delivery_id, CRMDelivery.tenant_id == principal.tenant_id)
        .with_for_update()
    )
    if not value:
        raise HTTPException(status_code=404, detail="CRM delivery not found")
    if value.acknowledged_at is not None:
        if value.verification_status not in {"failed", "auth_required", "retrying"}:
            raise HTTPException(status_code=409, detail="CRM verification is not retryable")
        value.status = CRMDeliveryStatus.ACKNOWLEDGED.value
        value.verification_status = "pending"
        value.verification_cycle_attempts = 0
        value.next_verification_at = datetime.now(UTC)
        value.verification_error_code = None
        value.verification_error_message = None
        phase = "verification"
    else:
        if value.status not in {"failed", "dead_letter", "mapping_error", "auth_required", "rate_limited"}:
            raise HTTPException(
                status_code=409, detail="CRM delivery is not retryable from its current state"
            )
        if value.last_error_code == "ambiguous_provider_ack":
            raise HTTPException(
                status_code=409,
                detail="Reconcile the provider record before retrying an ambiguous acknowledgement",
            )
        value.status = CRMDeliveryStatus.RETRYING.value
        value.retry_cycle_attempts = 0
        value.next_retry_at = datetime.now(UTC)
        value.last_error_message = None
        phase = "delivery"
    session.add(
        LeadActivityEvent(
            tenant_id=principal.tenant_id,
            lead_id=value.lead_id,
            event_type="lead.crm.retry.requested.v1",
            actor_type="user",
            actor_id=str(principal.user_id),
            correlation_id=request_id_ctx.get(),
            details_json={"deliveryId": str(value.id), "phase": phase},
        )
    )
    await session.commit()
    await session.refresh(value)
    return _delivery_out(value)


@router.post("/crm/deliveries/{delivery_id}/cancel", response_model=CRMDeliveryOut)
async def cancel_crm_delivery(delivery_id: UUID, principal: AdminPrincipal, session: DB) -> CRMDeliveryOut:
    value = await session.scalar(
        select(CRMDelivery)
        .where(CRMDelivery.id == delivery_id, CRMDelivery.tenant_id == principal.tenant_id)
        .with_for_update()
    )
    if not value:
        raise HTTPException(status_code=404, detail="CRM delivery not found")
    if value.acknowledged_at is not None or value.status in {
        "processing",
        "sent",
        "verifying",
        "verified",
        "cancelled",
    }:
        raise HTTPException(status_code=409, detail="CRM delivery cannot be cancelled")
    value.status = CRMDeliveryStatus.CANCELLED.value
    value.next_retry_at = None
    await session.commit()
    await session.refresh(value)
    return _delivery_out(value)


@router.post("/leads/{lead_id}/qualify")
async def qualify_lead(
    lead_id: UUID,
    payload: QualifyLeadRequest,
    principal: WorkspaceWritePrincipal,
    session: DB,
) -> dict[str, Any]:
    lead = await session.scalar(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.tenant_id == principal.tenant_id,
            Lead.workspace_id == principal.workspace_id,
            ~education_source(Lead),
        )
    )
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    profile = await lead_domain_service.qualify(
        session,
        lead=lead,
        score=payload.score,
        reason=payload.reason,
        actor_id=str(principal.user_id),
        correlation_id=request_id_ctx.get(),
    )
    await session.commit()
    return {
        "leadId": str(lead.id),
        "status": lead.status,
        "qualificationStatus": profile.qualification_status,
        "qualificationScore": profile.qualification_score,
        "qualificationReason": profile.qualification_reason,
    }


@router.post("/leads/{lead_id}/sync", status_code=202)
async def sync_lead(
    lead_id: UUID,
    payload: SyncLeadRequest,
    principal: WorkspaceWritePrincipal,
    session: DB,
) -> dict[str, Any]:
    lead = await session.scalar(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.tenant_id == principal.tenant_id,
            Lead.workspace_id == principal.workspace_id,
            ~education_source(Lead),
        )
    )
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    await lead_domain_service.request_sync(
        session,
        lead=lead,
        reason=payload.reason,
        correlation_id=request_id_ctx.get(),
        actor_id=str(principal.user_id),
    )
    await session.commit()
    return {"accepted": True, "leadId": str(lead.id), "requestId": request_id_ctx.get()}


@router.get("/leads/{lead_id}/deliveries", response_model=list[CRMDeliveryOut])
async def lead_deliveries(lead_id: UUID, principal: CurrentPrincipal, session: DB) -> list[CRMDeliveryOut]:
    exists = await session.scalar(
        select(Lead.id).where(
            Lead.id == lead_id,
            Lead.tenant_id == principal.tenant_id,
            Lead.workspace_id == principal.workspace_id,
            ~education_source(Lead),
        )
    )
    if not exists:
        raise HTTPException(status_code=404, detail="Lead not found")
    values = list(
        await session.scalars(
            select(CRMDelivery)
            .where(CRMDelivery.tenant_id == principal.tenant_id, CRMDelivery.lead_id == lead_id)
            .order_by(CRMDelivery.created_at.desc())
        )
    )
    return [_delivery_out(value) for value in values]


@router.get("/leads/{lead_id}/activity", response_model=list[LeadActivityOut])
async def lead_activity(lead_id: UUID, principal: CurrentPrincipal, session: DB) -> list[LeadActivityOut]:
    exists = await session.scalar(
        select(Lead.id).where(
            Lead.id == lead_id,
            Lead.tenant_id == principal.tenant_id,
            Lead.workspace_id == principal.workspace_id,
            ~education_source(Lead),
        )
    )
    if not exists:
        raise HTTPException(status_code=404, detail="Lead not found")
    values = list(
        await session.scalars(
            select(LeadActivityEvent)
            .where(LeadActivityEvent.tenant_id == principal.tenant_id, LeadActivityEvent.lead_id == lead_id)
            .order_by(LeadActivityEvent.occurred_at)
        )
    )
    return [
        LeadActivityOut(
            id=value.id,
            event_type=value.event_type,
            actor_type=value.actor_type,
            actor_id=value.actor_id,
            correlation_id=value.correlation_id,
            details=value.details_json,
            occurred_at=value.occurred_at,
        )
        for value in values
    ]
