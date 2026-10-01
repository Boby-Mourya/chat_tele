from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import EmailStr, Field, SecretStr, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import get_session
from northstar_api.dependencies import AdminPrincipal, require_permissions
from northstar_api.lead_crm.api_schemas import LeadCRMModel
from northstar_api.lead_crm.audit import record_audit_event
from northstar_api.lead_crm.connectors import CRMConnectionContext, CRMError, crm_registry
from northstar_api.lead_crm.credentials import CredentialStoreError, credential_store
from northstar_api.lead_crm.crm_provisioning import (
    DIRECT_CONNECT_PROVIDERS,
    MANAGED_OAUTH_PROVIDERS,
    connection_readiness,
    ensure_direct_connection,
    ensure_managed_oauth_connection,
    managed_provider_catalog,
    one_click_configuration,
    provision_connection,
)
from northstar_api.lead_crm.domain import CRMProvider, LeadLifecycleStatus, QualificationStatus
from northstar_api.lead_crm.models import CRMConnection, CRMDelivery, LeadActivityEvent
from northstar_api.lead_crm.services import lead_domain_service
from northstar_api.lead_crm.workspace_routing import workspace_crm_route_service
from northstar_api.lead_crm.workspace_scope import WorkspaceCRMConnection
from northstar_api.logging import request_id_ctx
from northstar_api.models import Agent, Lead
from northstar_api.routers.crm_oauth import _start_oauth
from northstar_api.security import Principal

router = APIRouter(tags=["crm-one-click"])
DB = Annotated[AsyncSession, Depends(get_session)]
CRMViewPrincipal = Annotated[Principal, Depends(require_permissions("crm.view"))]
CRMManagePrincipal = Annotated[Principal, Depends(require_permissions("crm.manage"))]


def _active_workspace_id(principal: Principal) -> UUID:
    if principal.workspace_id is None:
        raise HTTPException(status_code=403, detail="An active workspace is required")
    return principal.workspace_id


class OneClickCRMStart(LeadCRMModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    environment: Literal["production", "sandbox"] = "production"
    region: str | None = Field(default=None, max_length=16)
    resource_url: str | None = Field(default=None, max_length=512)
    azure_tenant_id: str | None = Field(default=None, max_length=128)
    client_id: str | None = Field(default=None, min_length=1, max_length=4096)
    client_secret: SecretStr | None = Field(default=None, min_length=1, max_length=4096)

    @model_validator(mode="after")
    def validate_client_credentials(self) -> OneClickCRMStart:
        if bool(self.client_id) != bool(self.client_secret):
            raise ValueError("Provide both the OAuth client ID and client secret")
        return self

    @field_validator("resource_url")
    @classmethod
    def validate_resource_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().rstrip("/")
        if not normalized.startswith("https://"):
            raise ValueError("resource_url must use HTTPS")
        return normalized


class DirectCRMConnectRequest(LeadCRMModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    base_url: str = Field(min_length=8, max_length=512)
    api_key: str | None = Field(default=None, min_length=1, max_length=4096)
    token: str | None = Field(default=None, min_length=1, max_length=4096)
    auth_type: Literal["NONE", "BEARER", "API_KEY_HEADER"] = "BEARER"
    api_key_header: str = Field(default="X-API-Key", min_length=1, max_length=120)
    health_path: str = Field(default="", max_length=512)
    upsert_path: str = Field(default="", max_length=512)
    get_path: str = Field(default="", max_length=512)
    external_id_path: str = Field(default="$.id", min_length=1, max_length=240)
    read_back_id_path: str = Field(default="id", min_length=1, max_length=240)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if not normalized.startswith("https://"):
            raise ValueError("base_url must use HTTPS")
        return normalized


class CRMAcceptanceTestRequest(LeadCRMModel):
    agent_id: UUID | None = None
    name: str = Field(default="Northstar CRM Acceptance Test", min_length=2, max_length=160)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=80)
    company: str = Field(default="Northstar Integration Test", min_length=1, max_length=240)


async def _scoped_connection(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    connection_id: UUID,
) -> CRMConnection | None:
    return await session.scalar(
        select(CRMConnection)
        .join(WorkspaceCRMConnection, WorkspaceCRMConnection.connection_id == CRMConnection.id)
        .where(
            CRMConnection.id == connection_id,
            CRMConnection.tenant_id == tenant_id,
            WorkspaceCRMConnection.tenant_id == tenant_id,
            WorkspaceCRMConnection.workspace_id == workspace_id,
        )
    )


@router.get("/crm/one-click/providers")
async def list_one_click_crm_providers(request: Request, principal: CRMViewPrincipal) -> list[dict[str, Any]]:
    del principal
    from northstar_api.config import get_settings

    settings = get_settings()
    base = (settings.crm_oauth_public_base_url or str(request.base_url)).rstrip("/")
    return [
        {
            **provider,
            "oauthRedirectUri": f"{base}{settings.app_api_prefix}/crm/oauth/{provider['id']}/callback",
        }
        for provider in managed_provider_catalog()
    ]


@router.post("/crm/one-click/{provider}/start")
async def start_one_click_crm(
    provider: str,
    payload: OneClickCRMStart,
    request: Request,
    principal: AdminPrincipal,
    session: DB,
) -> dict[str, Any]:
    workspace_id = _active_workspace_id(principal)
    try:
        provider_enum = CRMProvider(provider)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Unsupported CRM provider") from exc
    if provider_enum not in MANAGED_OAUTH_PROVIDERS:
        raise HTTPException(status_code=400, detail="This CRM provider does not support one-click OAuth")
    if provider_enum == CRMProvider.DYNAMICS365 and not payload.resource_url:
        raise HTTPException(status_code=422, detail="Dynamics 365 organization URL is required")
    try:
        configuration = one_click_configuration(
            provider_enum,
            environment=payload.environment,
            region=payload.region,
            resource_url=payload.resource_url,
            azure_tenant_id=payload.azure_tenant_id,
        )
        connection = await ensure_managed_oauth_connection(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=workspace_id,
            provider=provider_enum,
            display_name=payload.name,
            environment=payload.environment,
            region=payload.region,
            configuration=configuration,
            client_credentials={
                "client_id": payload.client_id,
                "client_secret": payload.client_secret.get_secret_value(),
            }
            if payload.client_id and payload.client_secret
            else None,
        )
    except CredentialStoreError as exc:
        raise HTTPException(status_code=503, detail="CRM credential encryption is not configured") from exc
    except (CRMError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    record_audit_event(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        actor_user_id=principal.user_id,
        action="crm.one_click.started",
        entity_type="crm_connection",
        entity_id=str(connection.id),
        category="crm",
        after={
            "provider": connection.provider,
            "environment": connection.environment,
            "status": connection.status,
            "managedOAuth": True,
        },
        metadata={"resourceUrlConfigured": bool(payload.resource_url)},
    )
    await session.commit()
    oauth = await _start_oauth(connection.id, request, principal, session, response_mode="popup")
    return {**oauth, "oneClick": True}


@router.post("/crm/one-click/{provider}/activate")
async def activate_direct_crm(
    provider: str,
    payload: DirectCRMConnectRequest,
    principal: AdminPrincipal,
    session: DB,
) -> dict[str, Any]:
    workspace_id = _active_workspace_id(principal)
    try:
        provider_enum = CRMProvider(provider)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Unsupported CRM provider") from exc
    if provider_enum not in DIRECT_CONNECT_PROVIDERS:
        raise HTTPException(status_code=400, detail="This CRM provider requires OAuth")

    if provider_enum == CRMProvider.FRESHSALES:
        if not payload.api_key:
            raise HTTPException(status_code=422, detail="Freshsales API key is required")
        configuration: dict[str, Any] = {"baseUrl": payload.base_url}
        credentials = {"api_key": payload.api_key}
    else:
        if not payload.upsert_path or not payload.get_path:
            raise HTTPException(status_code=422, detail="Generic REST upsert_path and get_path are required")
        if payload.auth_type == "BEARER" and not payload.token:
            raise HTTPException(status_code=422, detail="Bearer token is required")
        if payload.auth_type == "API_KEY_HEADER" and not payload.api_key:
            raise HTTPException(status_code=422, detail="API key is required")
        configuration = {
            "baseUrl": payload.base_url,
            "healthPath": payload.health_path,
            "upsertPath": payload.upsert_path,
            "createPath": payload.upsert_path,
            "getPath": payload.get_path,
            "updatePath": payload.get_path,
            "externalIdPath": payload.external_id_path,
            "readBackIdPath": payload.read_back_id_path,
            "auth": {
                "type": payload.auth_type,
                **({"name": payload.api_key_header} if payload.auth_type == "API_KEY_HEADER" else {}),
            },
        }
        credentials = {}
        if payload.token:
            credentials["token"] = payload.token
        if payload.api_key:
            credentials["api_key"] = payload.api_key
        if not credentials:
            credentials["auth_type"] = "none"

    try:
        connection = await ensure_direct_connection(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=workspace_id,
            provider=provider_enum,
            display_name=payload.name,
            configuration=configuration,
            credentials=credentials,
        )
        connector = crm_registry.get(provider_enum)
        context = CRMConnectionContext(
            tenant_id=principal.tenant_id,
            connection_id=connection.id,
            provider=provider_enum,
            configuration=dict(connection.configuration_json or {}),
            credentials=credentials,
        )
        health = await connector.health_check(context)
        connection.last_health_at = datetime.now(UTC)
        connection.status = health.status.value
        if health.status.value != "healthy":
            connection.last_failure_at = datetime.now(UTC)
            connection.last_error = str(health.details.get("error") or "Health validation failed")[:1000]
            await session.commit()
            raise HTTPException(status_code=409, detail="CRM health validation failed")
        result = await provision_connection(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=workspace_id,
            connection=connection,
            credentials=credentials,
        )
        record_audit_event(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=workspace_id,
            actor_user_id=principal.user_id,
            action="crm.one_click.connected",
            entity_type="crm_connection",
            entity_id=str(connection.id),
            category="crm",
            after={
                "provider": connection.provider,
                "status": connection.status,
                "ready": result.readiness.ready,
                "directConnect": True,
            },
        )
        await session.commit()
    except HTTPException:
        raise
    except CredentialStoreError as exc:
        raise HTTPException(status_code=503, detail="CRM credential encryption is not configured") from exc
    except (CRMError, ValueError) as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="CRM connection could not be activated") from exc
    return {**result.readiness.as_dict(), "schemaFieldCount": result.schema_field_count}


@router.get("/crm/connections/{connection_id}/readiness")
async def get_crm_connection_readiness(
    connection_id: UUID,
    principal: CRMViewPrincipal,
    session: DB,
) -> dict[str, Any]:
    workspace_id = _active_workspace_id(principal)
    connection = await _scoped_connection(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        connection_id=connection_id,
    )
    if connection is None:
        raise HTTPException(status_code=404, detail="CRM connection not found in this workspace")
    result = await connection_readiness(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        connection=connection,
    )
    return result.as_dict()


@router.post("/crm/connections/{connection_id}/provision")
async def provision_crm_connection(
    connection_id: UUID,
    principal: CRMManagePrincipal,
    session: DB,
) -> dict[str, Any]:
    workspace_id = _active_workspace_id(principal)
    connection = await _scoped_connection(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        connection_id=connection_id,
    )
    if connection is None:
        raise HTTPException(status_code=404, detail="CRM connection not found in this workspace")
    if not connection.credentials_encrypted:
        raise HTTPException(status_code=409, detail="CRM connection requires authorization")
    try:
        credentials = credential_store.decrypt(connection.credentials_encrypted)
        provider = CRMProvider(connection.provider)
        connector = crm_registry.get(provider)
        context = CRMConnectionContext(
            tenant_id=principal.tenant_id,
            connection_id=connection.id,
            provider=provider,
            configuration=dict(connection.configuration_json or {}),
            credentials=credentials,
        )
        health = await connector.health_check(context)
        if health.status.value != "healthy":
            connection.status = health.status.value
            connection.last_health_at = datetime.now(UTC)
            connection.last_error = str(health.details.get("error") or "CRM health validation failed")[:1000]
            await session.commit()
            raise HTTPException(status_code=409, detail="CRM connection is not healthy")
        result = await provision_connection(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=workspace_id,
            connection=connection,
            credentials=credentials,
        )
        await session.commit()
    except HTTPException:
        raise
    except (CRMError, CredentialStoreError, ValueError) as exc:
        connection.status = "configuration_error"
        connection.last_failure_at = datetime.now(UTC)
        connection.last_error = "CRM automatic provisioning failed"
        await session.commit()
        raise HTTPException(status_code=409, detail="CRM automatic provisioning failed") from exc
    return {
        **result.readiness.as_dict(),
        "schemaFieldCount": result.schema_field_count,
    }


@router.get("/crm/connections/{connection_id}/acceptance-test/{delivery_id}")
async def get_crm_acceptance_test_status(
    connection_id: UUID,
    delivery_id: UUID,
    principal: CRMViewPrincipal,
    session: DB,
) -> dict[str, Any]:
    workspace_id = _active_workspace_id(principal)
    delivery = await session.scalar(
        select(CRMDelivery)
        .join(Lead, Lead.id == CRMDelivery.lead_id)
        .where(
            CRMDelivery.id == delivery_id,
            CRMDelivery.connection_id == connection_id,
            CRMDelivery.tenant_id == principal.tenant_id,
            Lead.tenant_id == principal.tenant_id,
            Lead.workspace_id == workspace_id,
        )
    )
    if delivery is None:
        raise HTTPException(status_code=404, detail="CRM acceptance-test delivery not found")
    return {
        "connectionId": str(connection_id),
        "deliveryId": str(delivery.id),
        "leadId": str(delivery.lead_id),
        "provider": delivery.provider,
        "status": delivery.status,
        "acknowledged": delivery.acknowledged_at is not None,
        "acknowledgedAt": delivery.acknowledged_at,
        "verificationStatus": delivery.verification_status,
        "verified": delivery.verified_at is not None or delivery.status == "verified",
        "verifiedAt": delivery.verified_at,
        "externalRecordId": delivery.external_record_id,
        "providerRequestId": delivery.provider_request_id,
        "nextRetryAt": delivery.next_retry_at,
        "nextVerificationAt": delivery.next_verification_at,
        "errorCode": delivery.last_error_code or delivery.verification_error_code,
        "errorMessage": delivery.last_error_message or delivery.verification_error_message,
    }


@router.post("/crm/connections/{connection_id}/acceptance-test", status_code=202)
async def send_crm_acceptance_test(
    connection_id: UUID,
    payload: CRMAcceptanceTestRequest,
    principal: CRMManagePrincipal,
    session: DB,
) -> dict[str, Any]:
    workspace_id = _active_workspace_id(principal)
    connection = await _scoped_connection(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        connection_id=connection_id,
    )
    if connection is None:
        raise HTTPException(status_code=404, detail="CRM connection not found in this workspace")
    readiness = await connection_readiness(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        connection=connection,
    )
    if not readiness.ready:
        raise HTTPException(
            status_code=409,
            detail={"message": "CRM is not ready", "blockers": list(readiness.blockers)},
        )

    conditions: list[Any] = [
        Agent.tenant_id == principal.tenant_id,
        Agent.workspace_id == workspace_id,
    ]
    if payload.agent_id:
        conditions.append(Agent.id == payload.agent_id)
    agent = await session.scalar(select(Agent).where(*conditions).order_by(Agent.created_at))
    if payload.agent_id is not None and agent is None:
        raise HTTPException(status_code=404, detail="The selected Agent was not found in this workspace")
    if agent is None:
        agent = Agent(
            tenant_id=principal.tenant_id,
            workspace_id=workspace_id,
            name="CRM Acceptance Test Agent",
            description="Internal Agent used for CRM connection certification.",
        )
        session.add(agent)
        await session.flush()

    marker = uuid4().hex[:12]
    email = str(payload.email) if payload.email else f"northstar-crm-test+{marker}@example.com"
    lead = Lead(
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        agent_id=agent.id,
        conversation_id=None,
        name=payload.name,
        email=email,
        phone=payload.phone,
        status=LeadLifecycleStatus.QUALIFIED.value,
        consent=True,
        fields_json={
            "sourceChannel": "integration_test",
            "crmAcceptanceTest": True,
            "targetConnectionId": str(connection.id),
        },
    )
    session.add(lead)
    await session.flush()
    profile = await lead_domain_service.ensure_profile(
        session,
        lead=lead,
        source_channel="integration_test",
        source_provider="northstar",
        source_external_id=f"crm-test-{marker}",
    )
    first, _, last = payload.name.partition(" ")
    profile.first_name = first or payload.name
    profile.last_name = last or "Test"
    profile.company = payload.company
    profile.lifecycle_status = LeadLifecycleStatus.QUALIFIED.value
    profile.qualification_status = QualificationStatus.QUALIFIED.value
    profile.qualification_score = 100
    profile.qualification_reason = "Northstar one-click CRM live acceptance test"
    profile.consent_status = "granted"
    profile.qualified_at = datetime.now(UTC)
    session.add(
        LeadActivityEvent(
            tenant_id=principal.tenant_id,
            lead_id=lead.id,
            event_type="lead.crm.acceptance_test.started.v1",
            actor_type="user",
            actor_id=str(principal.user_id),
            correlation_id=request_id_ctx.get(),
            details_json={
                "workspaceId": str(workspace_id),
                "connectionId": str(connection.id),
                "provider": connection.provider,
            },
        )
    )
    deliveries = await workspace_crm_route_service.create_deliveries(
        session,
        tenant_id=principal.tenant_id,
        lead_id=lead.id,
        correlation_id=request_id_ctx.get(),
        sync_reason="manual",
        target_connection_id=connection.id,
    )
    if not deliveries:
        await session.rollback()
        raise HTTPException(status_code=409, detail="The CRM route did not create a delivery")
    record_audit_event(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        actor_user_id=principal.user_id,
        action="crm.acceptance_test.queued",
        entity_type="crm_delivery",
        entity_id=str(deliveries[0].id),
        category="crm",
        after={
            "leadId": str(lead.id),
            "connectionId": str(connection.id),
            "provider": connection.provider,
            "status": deliveries[0].status,
        },
    )
    await session.commit()
    return {
        "queued": True,
        "leadId": str(lead.id),
        "deliveryId": str(deliveries[0].id),
        "connectionId": str(connection.id),
        "provider": connection.provider,
        "status": deliveries[0].status,
        "message": "The test Lead is queued for provider ACK and read-back verification.",
    }
