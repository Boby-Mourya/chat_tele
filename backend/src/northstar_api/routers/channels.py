from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

import orjson
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import get_session, set_tenant_context
from northstar_api.dependencies import CurrentPrincipal, require_permissions
from northstar_api.lead_crm.channel_models import ChannelConnection, ChannelHealthSnapshot
from northstar_api.lead_crm.channel_scope import AgentChannelBinding, WorkspaceChannelConnection
from northstar_api.lead_crm.channels import ChannelConnectionContext, channel_registry
from northstar_api.lead_crm.credentials import CredentialStoreError, credential_store
from northstar_api.lead_crm.domain import ChannelProvider
from northstar_api.lead_crm.models import RawWebhookEvent
from northstar_api.models import Agent
from northstar_api.security import Principal
from northstar_api.services.outbox import enqueue_event

router = APIRouter(tags=["channels"])
DB = Annotated[AsyncSession, Depends(get_session)]
ChannelsViewPrincipal = Annotated[Principal, Depends(require_permissions("integrations.view"))]
ChannelsManagePrincipal = Annotated[Principal, Depends(require_permissions("integrations.manage"))]
MAX_WEBHOOK_BYTES = 1_048_576


class ChannelConnectionCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    provider: ChannelProvider
    name: str = Field(min_length=1, max_length=160)
    agent_id: UUID | None = Field(default=None, alias="agentId")
    configuration: dict[str, Any] = Field(default_factory=dict)
    credentials: dict[str, Any] = Field(default_factory=dict)


class ChannelConnectionOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    public_id: str
    workspace_id: UUID
    agent_id: UUID | None
    provider: str
    name: str
    status: str
    configuration: dict[str, Any]
    webhook_path: str
    last_health_at: datetime | None
    last_event_at: datetime | None
    last_failure_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


def _canonical_agent_channel(provider: ChannelProvider) -> str:
    if provider == ChannelProvider.WIDGET:
        return "website"
    if provider == ChannelProvider.FACEBOOK_MESSENGER:
        return "facebook"
    return provider.value


def _out(value: ChannelConnection, scope: WorkspaceChannelConnection) -> ChannelConnectionOut:
    return ChannelConnectionOut(
        id=value.id,
        public_id=value.public_id,
        workspace_id=scope.workspace_id,
        agent_id=scope.agent_id,
        provider=value.provider,
        name=value.name,
        status=value.status,
        configuration=value.configuration_json,
        webhook_path=(f"/api/v1/webhooks/channels/{value.tenant_id}/{value.provider}/{value.public_id}"),
        last_health_at=value.last_health_at,
        last_event_at=value.last_event_at,
        last_failure_at=value.last_failure_at,
        last_error=value.last_error,
        created_at=value.created_at,
        updated_at=value.updated_at,
    )


def _credentials(value: ChannelConnection) -> dict[str, Any]:
    if not value.credentials_encrypted:
        return {}
    try:
        return credential_store.decrypt(value.credentials_encrypted)
    except CredentialStoreError as exc:
        raise HTTPException(status_code=409, detail="Channel credentials require reconnection") from exc


def _context(value: ChannelConnection, credentials: dict[str, Any]) -> ChannelConnectionContext:
    return ChannelConnectionContext(
        tenant_id=value.tenant_id,
        connection_id=value.id,
        provider=ChannelProvider(value.provider),
        configuration=value.configuration_json,
        credentials=credentials,
        public_id=value.public_id,
    )


async def _scoped_connection(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    connection_id: UUID,
) -> tuple[ChannelConnection, WorkspaceChannelConnection] | None:
    row = (
        await session.execute(
            select(ChannelConnection, WorkspaceChannelConnection)
            .join(
                WorkspaceChannelConnection,
                WorkspaceChannelConnection.connection_id == ChannelConnection.id,
            )
            .where(
                ChannelConnection.id == connection_id,
                ChannelConnection.tenant_id == tenant_id,
                WorkspaceChannelConnection.tenant_id == tenant_id,
                WorkspaceChannelConnection.workspace_id == workspace_id,
            )
        )
    ).first()
    return (row[0], row[1]) if row else None


async def _validate_agent_channel(
    session: AsyncSession,
    principal: Principal,
    provider: ChannelProvider,
    agent_id: UUID | None,
) -> None:
    if agent_id is None:
        return
    agent = await session.scalar(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.tenant_id == principal.tenant_id,
            Agent.workspace_id == principal.workspace_id,
            Agent.deleted_at.is_(None),
        )
    )
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found in this workspace")
    binding = await session.scalar(
        select(AgentChannelBinding).where(
            AgentChannelBinding.tenant_id == principal.tenant_id,
            AgentChannelBinding.workspace_id == principal.workspace_id,
            AgentChannelBinding.agent_id == agent_id,
        )
    )
    expected = _canonical_agent_channel(provider)
    if binding and binding.channel_type != expected:
        raise HTTPException(
            status_code=409,
            detail=f"Agent is assigned to {binding.channel_type}; it cannot use a {expected} connection",
        )


@router.get("/channels/providers")
async def channel_providers(_: CurrentPrincipal) -> list[dict[str, Any]]:
    registered = set(channel_registry.providers())
    return [
        {
            "id": provider.value,
            "name": provider.value.replace("_", " ").title(),
            "runtimeRegistered": provider in registered,
        }
        for provider in ChannelProvider
    ]


@router.post("/channels/connections", response_model=ChannelConnectionOut, status_code=201)
async def create_channel_connection(
    payload: ChannelConnectionCreate,
    principal: ChannelsManagePrincipal,
    session: DB,
) -> ChannelConnectionOut:
    if payload.provider == ChannelProvider.TELEGRAM and payload.configuration.get("telegram", {}).get("managed"):
        raise HTTPException(422, "Managed Telegram bots must use the Connect flow")
    await _validate_agent_channel(session, principal, payload.provider, payload.agent_id)
    duplicate = await session.scalar(
        select(ChannelConnection.id)
        .join(
            WorkspaceChannelConnection,
            WorkspaceChannelConnection.connection_id == ChannelConnection.id,
        )
        .where(
            ChannelConnection.tenant_id == principal.tenant_id,
            ChannelConnection.name == payload.name,
            WorkspaceChannelConnection.workspace_id == principal.workspace_id,
        )
    )
    if duplicate:
        raise HTTPException(
            status_code=409, detail="A channel connection with that name already exists in this workspace"
        )
    try:
        channel_registry.get(payload.provider)
    except KeyError as exc:
        raise HTTPException(
            status_code=409, detail="Channel connector is not available in this runtime"
        ) from exc
    encrypted = None
    if payload.credentials:
        try:
            encrypted = credential_store.encrypt(payload.credentials)
        except CredentialStoreError as exc:
            raise HTTPException(status_code=503, detail="Credential encryption is not configured") from exc

    stored_name = payload.name
    tenant_conflict = await session.scalar(
        select(ChannelConnection.id).where(
            ChannelConnection.tenant_id == principal.tenant_id,
            ChannelConnection.name == stored_name,
        )
    )
    if tenant_conflict:
        stored_name = f"{payload.name} [{str(principal.workspace_id)[:8]}]"

    value = ChannelConnection(
        tenant_id=principal.tenant_id,
        public_id=f"chn_{uuid.uuid4().hex}",
        provider=payload.provider.value,
        name=stored_name,
        status="configured" if encrypted or payload.configuration else "draft",
        credentials_encrypted=encrypted,
        configuration_json=payload.configuration,
    )
    session.add(value)
    await session.flush()
    scope = WorkspaceChannelConnection(
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        agent_id=payload.agent_id,
        connection_id=value.id,
    )
    session.add(scope)
    await session.commit()
    await session.refresh(value)
    await session.refresh(scope)
    return _out(value, scope)


@router.get("/channels/connections", response_model=list[ChannelConnectionOut])
async def list_channel_connections(
    principal: ChannelsViewPrincipal,
    session: DB,
) -> list[ChannelConnectionOut]:
    rows = (
        await session.execute(
            select(ChannelConnection, WorkspaceChannelConnection)
            .join(
                WorkspaceChannelConnection,
                WorkspaceChannelConnection.connection_id == ChannelConnection.id,
            )
            .where(
                ChannelConnection.tenant_id == principal.tenant_id,
                WorkspaceChannelConnection.tenant_id == principal.tenant_id,
                WorkspaceChannelConnection.workspace_id == principal.workspace_id,
            )
            .order_by(ChannelConnection.created_at.desc())
        )
    ).all()
    return [_out(value, scope) for value, scope in rows]


@router.patch("/channels/connections/{connection_id}", response_model=ChannelConnectionOut)
async def update_channel_connection(
    connection_id: UUID,
    payload: ChannelConnectionCreate,
    principal: ChannelsManagePrincipal,
    session: DB,
) -> ChannelConnectionOut:
    scoped = await _scoped_connection(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        connection_id=connection_id,
    )
    if not scoped:
        raise HTTPException(status_code=404, detail="Channel connection not found in this workspace")
    value, scope = scoped
    if value.provider == "telegram" and ((value.configuration_json or {}).get("telegram", {}).get("managed") or payload.configuration.get("telegram", {}).get("managed")):
        raise HTTPException(409, "Use Connect or Disconnect for managed Telegram bots")
    if value.provider != payload.provider.value:
        raise HTTPException(status_code=422, detail="A connection's provider cannot be changed")
    await _validate_agent_channel(session, principal, payload.provider, payload.agent_id)
    # Keep the existing name and public webhook URL stable when replacing credentials.
    if not payload.credentials:
        raise HTTPException(status_code=422, detail="Replacement credentials are required")
    try:
        value.credentials_encrypted = credential_store.encrypt(payload.credentials)
    except CredentialStoreError as exc:
        raise HTTPException(status_code=503, detail="Credential encryption is not configured") from exc
    value.configuration_json = payload.configuration
    scope.agent_id = payload.agent_id
    value.status = "configured"
    value.last_error = None
    value.last_health_at = None
    value.last_event_at = None
    await session.commit()
    await session.refresh(value)
    return _out(value, scope)


@router.post("/channels/connections/{connection_id}/test")
async def test_channel_connection(
    connection_id: UUID,
    principal: ChannelsManagePrincipal,
    session: DB,
) -> dict[str, Any]:
    scoped = await _scoped_connection(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        connection_id=connection_id,
    )
    if not scoped:
        raise HTTPException(status_code=404, detail="Channel connection not found in this workspace")
    value, _ = scoped
    credentials = _credentials(value)
    if value.provider == "telegram":
        await session.refresh(value, with_for_update=True)
        if value.status == "disabled":
            raise HTTPException(409, "Telegram connection is disabled")
        credentials = _credentials(value)
    connector = channel_registry.get(ChannelProvider(value.provider))
    result = await connector.health_check(_context(value, credentials))
    checked_at = datetime.now(UTC)
    value.last_health_at = checked_at
    value.status = result.get("status", "unknown")
    value.last_error = None if value.status == "healthy" else "Channel health validation failed"
    session.add(
        ChannelHealthSnapshot(
            tenant_id=principal.tenant_id,
            connection_id=value.id,
            status=str(value.status or "unknown")[:40],
            error_code=None,
            checked_at=checked_at,
        )
    )
    await session.commit()
    return result


@router.delete("/channels/connections/{connection_id}", status_code=204)
async def disable_channel_connection(
    connection_id: UUID,
    principal: ChannelsManagePrincipal,
    session: DB,
) -> None:
    scoped = await _scoped_connection(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        connection_id=connection_id,
    )
    if not scoped:
        raise HTTPException(status_code=404, detail="Channel connection not found in this workspace")
    value, _ = scoped
    if value.provider == "telegram":
        from northstar_api.services.telegram_provisioning import disconnect
        await disconnect(session, value)
        await session.commit()
        return
    value.status = "disabled"
    value.credentials_encrypted = None
    value.credentials_ref = None
    await session.commit()


async def _external_connection(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    provider: ChannelProvider,
    public_id: str,
) -> tuple[ChannelConnection, WorkspaceChannelConnection] | None:
    row = (
        await session.execute(
            select(ChannelConnection, WorkspaceChannelConnection)
            .join(
                WorkspaceChannelConnection,
                WorkspaceChannelConnection.connection_id == ChannelConnection.id,
            )
            .where(
                ChannelConnection.tenant_id == tenant_id,
                ChannelConnection.public_id == public_id,
                ChannelConnection.provider == provider.value,
                ChannelConnection.status != "disabled",
                WorkspaceChannelConnection.tenant_id == tenant_id,
            )
        )
    ).first()
    return (row[0], row[1]) if row else None


@router.get("/webhooks/channels/{tenant_id}/{provider}/{public_id}", include_in_schema=False)
async def verify_meta_channel_webhook(
    tenant_id: UUID,
    provider: ChannelProvider,
    public_id: str,
    session: DB,
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
) -> Response:
    if provider not in {
        ChannelProvider.WHATSAPP,
        ChannelProvider.INSTAGRAM,
        ChannelProvider.FACEBOOK_MESSENGER,
    }:
        raise HTTPException(status_code=404, detail="Webhook verification is not supported")
    await set_tenant_context(session, tenant_id)
    scoped = await _external_connection(session, tenant_id=tenant_id, provider=provider, public_id=public_id)
    if not scoped:
        raise HTTPException(status_code=404, detail="Channel connection not found")
    value, _ = scoped
    credentials = _credentials(value)
    expected = str(credentials.get("verify_token") or "")
    if (
        hub_mode != "subscribe"
        or not expected
        or not hub_verify_token
        or not hmac.compare_digest(expected.encode(), hub_verify_token.encode())
        or hub_challenge is None
    ):
        raise HTTPException(status_code=403, detail="Webhook verification failed")
    return Response(content=hub_challenge, media_type="text/plain")


@router.post("/webhooks/channels/{tenant_id}/{provider}/{public_id}", include_in_schema=False)
async def receive_channel_webhook(
    tenant_id: UUID,
    provider: ChannelProvider,
    public_id: str,
    request: Request,
    session: DB,
) -> dict[str, Any]:
    body = await request.body()
    if len(body) > MAX_WEBHOOK_BYTES:
        raise HTTPException(status_code=413, detail="Webhook payload is too large")
    try:
        payload = orjson.loads(body)
    except orjson.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Webhook payload is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Webhook payload must be an object")

    await set_tenant_context(session, tenant_id)
    scoped = await _external_connection(session, tenant_id=tenant_id, provider=provider, public_id=public_id)
    if not scoped:
        raise HTTPException(status_code=404, detail="Channel connection not found")
    connection, scope = scoped
    if provider == ChannelProvider.TELEGRAM:
        await session.refresh(connection, with_for_update=True)
        if connection.status == "disabled":
            raise HTTPException(status_code=404, detail="Channel connection not found")
    credentials = _credentials(connection)
    connector = channel_registry.get(provider)
    headers = {key.lower(): value for key, value in request.headers.items()}
    if not await connector.verify(_context(connection, credentials), headers=headers, body=body):
        connection.last_failure_at = datetime.now(UTC)
        connection.last_error = "Webhook signature/secret verification failed"
        await session.commit()
        raise HTTPException(status_code=401, detail="Webhook verification failed")

    correlation_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    received_at = datetime.now(UTC)
    normalized = await connector.normalize(
        _context(connection, credentials),
        payload=payload,
        correlation_id=correlation_id,
        received_at=received_at,
    )
    if not normalized:
        fallback_id = hashlib.sha256(body).hexdigest()
        external_ids = [(fallback_id, "provider.notification")]
    else:
        external_ids = [(event.external_event_id, event.event_type) for event in normalized]

    stored = 0
    for external_id, event_type in external_ids:
        existing = await session.scalar(
            select(RawWebhookEvent.id).where(
                RawWebhookEvent.tenant_id == tenant_id,
                RawWebhookEvent.provider == provider.value,
                RawWebhookEvent.connection_key == str(connection.id),
                RawWebhookEvent.external_event_id == external_id,
            )
        )
        if existing:
            continue
        raw_event = RawWebhookEvent(
            tenant_id=tenant_id,
            connection_key=str(connection.id),
            provider=provider.value,
            external_event_id=external_id,
            event_type=event_type,
            payload_json=payload,
            headers_json={
                "content-type": request.headers.get("content-type"),
                "user-agent": request.headers.get("user-agent"),
            },
            payload_hash=hashlib.sha256(body).hexdigest(),
            verification_status="verified",
            processing_status="received",
            received_at=received_at,
            correlation_id=correlation_id,
        )
        try:
            async with session.begin_nested():
                session.add(raw_event)
                await session.flush()
        except IntegrityError:
            continue
        enqueue_event(
            session,
            tenant_id=tenant_id,
            aggregate_type="raw_webhook_event",
            aggregate_id=raw_event.id,
            event_type="channel.event.received.v1",
            payload={
                "rawEventId": str(raw_event.id),
                "provider": provider.value,
                "workspaceId": str(scope.workspace_id),
                "agentId": str(scope.agent_id) if scope.agent_id else None,
                "channelConnectionId": str(connection.id),
            },
        )
        stored += 1

    connection.last_event_at = received_at
    if not (provider == ChannelProvider.TELEGRAM and (connection.configuration_json or {}).get("telegram", {}).get("managed")):
        connection.status = "healthy"
        connection.last_error = None
    await session.commit()
    return {
        "acknowledged": True,
        "acceptedEvents": stored,
        "correlationId": correlation_id,
        "workspaceId": str(scope.workspace_id),
        "agentId": str(scope.agent_id) if scope.agent_id else None,
    }
