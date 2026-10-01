from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from redis.exceptions import RedisError
from sqlalchemy import delete, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from northstar_api.config import get_settings
from northstar_api.database import engine, get_session
from northstar_api.dependencies import AdminPrincipal, require_permissions
from northstar_api.models import (
    Agent,
    AgentStatus,
    Channel,
    Conversation,
    ConversationState,
    IntegrationConnection,
    Message,
    WhatsAppConnection,
    WhatsAppDeliveryReceipt,
    WhatsAppInboundMessage,
    WhatsAppOutboundDelivery,
)
from northstar_api.schemas import (
    IntegrationOut,
    IntegrationPatch,
    WhatsAppBootstrapOut,
    WhatsAppCompleteRequest,
    WhatsAppConnectionOut,
    WhatsAppStatusOut,
)
from northstar_api.modules.whatsapp.accounts import connection_client
from northstar_api.modules.whatsapp.graph import (
    WhatsAppConfigurationError,
    WhatsAppGraphError,
    token_cipher,
    token_expiry_is_current,
    whatsapp_client,
)
from northstar_api.security import Principal, create_whatsapp_signup_token, decode_token
from northstar_api.services.outbox import enqueue_event
from northstar_api.services.rate_limit import redis_services
from northstar_api.workers.tasks import whatsapp_thread_lock_key

router = APIRouter(prefix="/integrations", tags=["integrations"])
DB = Annotated[AsyncSession, Depends(get_session)]
IntegrationsViewPrincipal = Annotated[Principal, Depends(require_permissions("integrations.view"))]
IntegrationsManagePrincipal = Annotated[Principal, Depends(require_permissions("integrations.manage"))]
_local_setup_lock = asyncio.Lock()

CATALOG: tuple[dict[str, Any], ...] = (
    {
        "id": "website",
        "name": "Website widget",
        "description": "Embed the agent on any website.",
        "category": "channel",
        "icon": "code",
    },
    {
        "id": "telegram",
        "name": "Telegram",
        "description": "Connect a Telegram bot to your agent.",
        "category": "channel",
        "icon": "message",
    },
    {
        "id": "slack",
        "name": "Slack",
        "description": "Answer questions in Slack.",
        "category": "channel",
        "icon": "hash",
    },
    {
        "id": "whatsapp",
        "name": "WhatsApp",
        "description": "Support WhatsApp Business customers.",
        "category": "channel",
        "icon": "message",
    },
    {
        "id": "facebook",
        "name": "Facebook Messenger",
        "description": "Deploy the agent to a Facebook Page inbox.",
        "category": "channel",
        "icon": "facebook",
    },
    {
        "id": "instagram",
        "name": "Instagram",
        "description": "Answer customer messages from Instagram.",
        "category": "channel",
        "icon": "instagram",
    },
    {
        "id": "zapier",
        "name": "Zapier",
        "description": "Trigger workflows from events.",
        "category": "automation",
        "icon": "zap",
    },
    {
        "id": "notion",
        "name": "Notion",
        "description": "Sync selected knowledge pages.",
        "category": "data",
        "icon": "book",
    },
    {
        "id": "api",
        "name": "Developer API",
        "description": "Use REST and streaming APIs.",
        "category": "developer",
        "icon": "terminal",
    },
    {
        "id": "teams",
        "name": "Microsoft Teams",
        "description": "Bring answers into Teams.",
        "category": "channel",
        "icon": "users",
        "comingSoon": True,
    },
)


def whatsapp_setup_lock_keys(tenant_id: UUID, phone_number_id: str) -> tuple[str, str]:
    # The category order is invariant across callers, preventing lock cycles.
    return (f"whatsapp-setup:tenant:{tenant_id}", f"whatsapp-setup:phone:{phone_number_id}")


async def serialize_whatsapp_setup(
    payload: WhatsAppCompleteRequest,
    principal: AdminPrincipal,
) -> AsyncIterator[None]:
    keys = whatsapp_setup_lock_keys(principal.tenant_id, payload.phone_number_id)
    if engine.dialect.name == "postgresql":
        async with engine.connect() as lock_connection:
            async with lock_connection.begin():
                for key in keys:
                    locked = bool(
                        await lock_connection.scalar(
                            text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key, 0))"),
                            {"key": key},
                        )
                    )
                    if not locked:
                        raise HTTPException(
                            status_code=409,
                            detail="Another WhatsApp setup is already in progress",
                        )
                yield
        return

    if _local_setup_lock.locked():
        raise HTTPException(status_code=409, detail="Another WhatsApp setup is already in progress")
    async with _local_setup_lock:
        yield


WhatsAppSetupLock = Annotated[None, Depends(serialize_whatsapp_setup)]


async def integration_list(
    session: AsyncSession, tenant_id: UUID, workspace_id: UUID
) -> list[IntegrationOut]:
    states = {
        item.integration_id: item.connected
        for item in (
            await session.scalars(
                select(IntegrationConnection).where(
                    IntegrationConnection.tenant_id == tenant_id,
                    IntegrationConnection.workspace_id == workspace_id,
                )
            )
        ).all()
    }
    whatsapp_connections = list(
        await session.scalars(
            select(WhatsAppConnection).where(
                WhatsAppConnection.tenant_id == tenant_id,
                WhatsAppConnection.workspace_id == workspace_id,
                WhatsAppConnection.status == "connected",
            )
        )
    )
    states["whatsapp"] = any(_token_is_current(item) for item in whatsapp_connections)
    return [
        IntegrationOut.model_validate(
            {
                **item,
                "connected": states.get(item["id"], item["id"] in {"website", "api"}),
                "comingSoon": item.get("comingSoon", False),
            }
        )
        for item in CATALOG
    ]


@router.get("", response_model=list[IntegrationOut])
async def list_integrations(principal: IntegrationsViewPrincipal, session: DB) -> list[IntegrationOut]:
    assert principal.workspace_id is not None
    return await integration_list(session, principal.tenant_id, principal.workspace_id)


@router.patch("/{integration_id}", response_model=IntegrationOut)
async def update_integration(
    integration_id: str, payload: IntegrationPatch, principal: IntegrationsManagePrincipal, session: DB
) -> IntegrationOut:
    catalog_entry = next((item for item in CATALOG if item["id"] == integration_id), None)
    if not catalog_entry:
        raise HTTPException(status_code=404, detail="Integration not found")
    if catalog_entry.get("comingSoon"):
        raise HTTPException(status_code=409, detail="Integration is not available yet")
    if integration_id == "whatsapp":
        raise HTTPException(
            status_code=409,
            detail="Use WhatsApp Embedded Signup to connect or disconnect a phone number",
        )
    connection = await session.scalar(
        select(IntegrationConnection).where(
            IntegrationConnection.tenant_id == principal.tenant_id,
            IntegrationConnection.workspace_id == principal.workspace_id,
            IntegrationConnection.integration_id == integration_id,
        )
    )
    if not connection:
        connection = IntegrationConnection(
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            integration_id=integration_id,
            connected=payload.connected,
        )
        session.add(connection)
    else:
        connection.connected = payload.connected
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="integration",
        aggregate_id=integration_id,
        event_type="integration.connection.changed.v1",
        payload={"integrationId": integration_id, "connected": payload.connected},
    )
    await session.commit()
    return IntegrationOut.model_validate(
        {
            **catalog_entry,
            "connected": payload.connected,
            "comingSoon": catalog_entry.get("comingSoon", False),
        }
    )


def _token_is_current(connection: WhatsAppConnection) -> bool:
    return token_expiry_is_current(connection.token_expires_at)


def whatsapp_connection_response(
    connection: WhatsAppConnection, *, status_override: str | None = None
) -> WhatsAppConnectionOut:
    return WhatsAppConnectionOut(
        id=connection.id,
        business_account_id=connection.business_account_id,
        waba_id=connection.waba_id,
        phone_number_id=connection.phone_number_id,
        display_phone_number=connection.display_phone_number,
        verified_name=connection.verified_name,
        agent_id=connection.agent_id,
        status=status_override or connection.status,
        token_expires_at=connection.token_expires_at,
        connected_at=connection.connected_at,
    )


async def whatsapp_status(session: AsyncSession, tenant_id: UUID, workspace_id: UUID) -> WhatsAppStatusOut:
    settings = get_settings()
    connections = list(
        await session.scalars(
            select(WhatsAppConnection)
            .where(
                WhatsAppConnection.tenant_id == tenant_id,
                WhatsAppConnection.workspace_id == workspace_id,
            )
            .order_by(WhatsAppConnection.connected_at, WhatsAppConnection.id)
        )
    )
    responses = [
        whatsapp_connection_response(
            connection,
            status_override=(
                "reconnect_required"
                if connection.status == "connected" and not _token_is_current(connection)
                else connection.status
            ),
        )
        for connection in connections
    ]
    token_current = any(item.status == "connected" and _token_is_current(item) for item in connections)
    return WhatsAppStatusOut(
        enabled=settings.whatsapp_configured,
        connected=token_current,
        connection=responses[0] if responses else None,
        connections=responses,
    )


@router.get("/whatsapp/bootstrap", response_model=WhatsAppBootstrapOut)
async def whatsapp_bootstrap(
    principal: IntegrationsManagePrincipal, session: DB, request: Request
) -> WhatsAppBootstrapOut:
    settings = get_settings()
    assert principal.workspace_id is not None
    status = await whatsapp_status(session, principal.tenant_id, principal.workspace_id)
    signup_session = None
    if status.enabled:
        signup_session, _ = create_whatsapp_signup_token(principal.user_id, principal.tenant_id, settings)
    return WhatsAppBootstrapOut(
        webhook_url=f"{(settings.crm_oauth_public_base_url or str(request.base_url)).rstrip('/')}/api/v1/webhooks/whatsapp",
        missing_settings=[
            key.upper()
            for key in (
                "meta_app_id",
                "meta_app_secret",
                "meta_whatsapp_configuration_id",
                "meta_whatsapp_webhook_verify_token",
                "meta_whatsapp_token_encryption_key",
            )
            if not getattr(settings, key)
        ],
        enabled=status.enabled,
        connected=status.connected,
        connection=status.connection,
        connections=status.connections,
        app_id=settings.meta_app_id if status.enabled else None,
        configuration_id=(settings.meta_whatsapp_configuration_id if status.enabled else None),
        api_version=settings.meta_graph_api_version,
        signup_session=signup_session,
    )


@router.get("/whatsapp/status", response_model=WhatsAppStatusOut)
async def get_whatsapp_status(principal: IntegrationsViewPrincipal, session: DB) -> WhatsAppStatusOut:
    assert principal.workspace_id is not None
    return await whatsapp_status(session, principal.tenant_id, principal.workspace_id)


@router.get("/whatsapp/{agent_id}/templates")
async def whatsapp_templates(
    agent_id: UUID, principal: IntegrationsViewPrincipal, session: DB
) -> list[dict[str, Any]]:
    from northstar_api.modules.whatsapp.templates import template_fields

    connection = await session.scalar(
        select(WhatsAppConnection).where(
            WhatsAppConnection.tenant_id == principal.tenant_id,
            WhatsAppConnection.workspace_id == principal.workspace_id,
            WhatsAppConnection.agent_id == agent_id,
            WhatsAppConnection.status == "connected",
        )
    )
    if connection is None:
        raise HTTPException(status_code=404, detail="WhatsApp connection not found")
    try:
        provider_client, access_token = await connection_client(session, connection)
        templates = await provider_client.list_templates(access_token, waba_id=connection.waba_id)
    except (WhatsAppGraphError, WhatsAppConfigurationError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    result = []
    for template in templates:
        try:
            fields = template_fields(template)
            reason = None
        except ValueError as exc:
            fields, reason = [], str(exc)
        result.append(
            {
                "name": template["name"],
                "language": template["language"],
                "fields": fields,
                "preview": "\n".join(item.get("text", "") for item in template.get("components", [])),
                "unsupportedReason": reason,
            }
        )
    return result


@router.get("/whatsapp/{agent_id}/activity")
async def whatsapp_activity(
    agent_id: UUID, principal: IntegrationsViewPrincipal, session: DB
) -> dict[str, Any]:
    connection = await session.scalar(
        select(WhatsAppConnection).where(
            WhatsAppConnection.tenant_id == principal.tenant_id,
            WhatsAppConnection.workspace_id == principal.workspace_id,
            WhatsAppConnection.agent_id == agent_id,
        )
    )
    if connection is None:
        raise HTTPException(status_code=404, detail="WhatsApp connection not found")
    inbound = list(
        await session.scalars(
            select(WhatsAppInboundMessage)
            .where(
                WhatsAppInboundMessage.tenant_id == principal.tenant_id,
                WhatsAppInboundMessage.workspace_id == principal.workspace_id,
                WhatsAppInboundMessage.connection_id == connection.id,
            )
            .order_by(WhatsAppInboundMessage.created_at.desc())
            .limit(30)
        )
    )
    outbound = list(
        await session.scalars(
            select(WhatsAppOutboundDelivery)
            .where(
                WhatsAppOutboundDelivery.tenant_id == principal.tenant_id,
                WhatsAppOutboundDelivery.workspace_id == principal.workspace_id,
                WhatsAppOutboundDelivery.connection_id == connection.id,
            )
            .order_by(WhatsAppOutboundDelivery.created_at.desc())
            .limit(30)
        )
    )
    receipts = list(
        await session.scalars(
            select(WhatsAppDeliveryReceipt)
            .where(
                WhatsAppDeliveryReceipt.tenant_id == principal.tenant_id,
                WhatsAppDeliveryReceipt.workspace_id == principal.workspace_id,
                WhatsAppDeliveryReceipt.connection_id == connection.id,
            )
            .order_by(WhatsAppDeliveryReceipt.provider_timestamp.desc())
            .limit(50)
        )
    )
    return {
        "lastError": connection.last_error,
        "outbound": [
            {"id": str(item.id), "status": item.status, "at": item.created_at, "error": item.last_error}
            for item in outbound
        ],
        "inbound": [
            {
                "id": str(item.id),
                "status": item.status,
                "messageType": item.message_type,
                "receivedAt": item.created_at,
                "conversationId": str(item.conversation_id) if item.conversation_id else None,
                "error": item.last_error,
            }
            for item in inbound
        ],
        "deliveries": [
            {
                "id": item.provider_message_id,
                "status": item.status,
                "at": item.provider_timestamp,
                "errorCode": item.error_code,
            }
            for item in receipts
        ],
    }


@router.post("/whatsapp/{agent_id}/check", response_model=WhatsAppConnectionOut)
async def check_whatsapp_connection(
    agent_id: UUID, principal: IntegrationsManagePrincipal, session: DB
) -> WhatsAppConnectionOut:
    connection = await session.scalar(
        select(WhatsAppConnection).where(
            WhatsAppConnection.tenant_id == principal.tenant_id,
            WhatsAppConnection.workspace_id == principal.workspace_id,
            WhatsAppConnection.agent_id == agent_id,
        )
    )
    if connection is None:
        raise HTTPException(status_code=404, detail="WhatsApp connection not found")
    try:
        provider_client, token = await connection_client(session, connection)
        expires_at = await provider_client.validate_token(token)
        number, name = await provider_client.get_phone_for_waba(
            token, waba_id=connection.waba_id, phone_number_id=connection.phone_number_id
        )
    except (WhatsAppGraphError, WhatsAppConfigurationError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    connection.token_expires_at = expires_at
    connection.display_phone_number = number
    connection.verified_name = name
    await session.commit()
    return whatsapp_connection_response(connection)


@router.post("/whatsapp/complete", response_model=WhatsAppConnectionOut)
async def complete_whatsapp_signup(
    payload: WhatsAppCompleteRequest,
    principal: IntegrationsManagePrincipal,
    session: DB,
    _setup_lock: WhatsAppSetupLock,
) -> WhatsAppConnectionOut:
    settings = get_settings()
    if not settings.whatsapp_configured:
        raise HTTPException(status_code=503, detail="WhatsApp integration is not configured")
    await _consume_whatsapp_signup_session(
        payload.signup_session,
        user_id=principal.user_id,
        tenant_id=principal.tenant_id,
    )
    agent = await session.scalar(
        select(Agent).where(
            Agent.id == payload.agent_id,
            Agent.tenant_id == principal.tenant_id,
            Agent.workspace_id == principal.workspace_id,
            Agent.deleted_at.is_(None),
        )
    )
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent.status != AgentStatus.ACTIVE:
        raise HTTPException(
            status_code=409,
            detail="Publish the agent before connecting it to WhatsApp",
        )
    current_connection = await session.scalar(
        select(WhatsAppConnection).where(
            WhatsAppConnection.tenant_id == principal.tenant_id,
            WhatsAppConnection.workspace_id == principal.workspace_id,
            WhatsAppConnection.agent_id == payload.agent_id,
        )
    )
    if current_connection and (
        current_connection.waba_id != payload.waba_id
        or current_connection.phone_number_id != payload.phone_number_id
    ):
        raise HTTPException(
            status_code=409,
            detail="Disconnect this bot's current WhatsApp number before selecting a different one",
        )
    if session.bind and session.bind.dialect.name == "postgresql":
        phone_owner = await session.scalar(
            text("SELECT northstar_find_whatsapp_phone_owner(:phone_number_id)"),
            {"phone_number_id": payload.phone_number_id},
        )
    else:
        phone_owner = await session.scalar(
            select(WhatsAppConnection.tenant_id).where(
                WhatsAppConnection.phone_number_id == payload.phone_number_id
            )
        )
    phone_connection = await session.scalar(
        select(WhatsAppConnection).where(WhatsAppConnection.phone_number_id == payload.phone_number_id)
    )
    if phone_owner is not None and UUID(str(phone_owner)) != principal.tenant_id:
        raise HTTPException(
            status_code=409,
            detail="That WhatsApp phone number is already connected to another workspace",
        )
    if phone_connection is not None and phone_connection.agent_id != payload.agent_id:
        raise HTTPException(
            status_code=409,
            detail="That WhatsApp phone number is already dedicated to another bot",
        )
    try:
        setup = await whatsapp_client.complete_setup(
            code=payload.code,
            waba_id=payload.waba_id,
            phone_number_id=payload.phone_number_id,
            registration_pin=payload.two_step_verification_pin,
        )
        encrypted_token = token_cipher.encrypt(setup.access_token)
    except WhatsAppConfigurationError:
        raise HTTPException(status_code=503, detail="WhatsApp integration is not configured") from None
    except WhatsAppGraphError:
        raise HTTPException(
            status_code=502,
            detail="Meta could not verify or connect the selected WhatsApp number",
        ) from None

    connection = current_connection
    if not connection:
        connection = WhatsAppConnection(
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            agent_id=payload.agent_id,
            waba_id=payload.waba_id,
            phone_number_id=payload.phone_number_id,
            display_phone_number=setup.display_phone_number,
            verified_name=setup.verified_name,
            access_token_encrypted=encrypted_token,
            token_expires_at=setup.expires_at,
            status="connected",
            connected_at=datetime.now(UTC),
        )
        session.add(connection)
    else:
        connection.agent_id = payload.agent_id
        connection.waba_id = payload.waba_id
        connection.phone_number_id = payload.phone_number_id
        connection.display_phone_number = setup.display_phone_number
        connection.verified_name = setup.verified_name
        connection.access_token_encrypted = encrypted_token
        connection.token_expires_at = setup.expires_at
        connection.status = "connected"
        connection.last_error = None
        connection.connected_at = datetime.now(UTC)

    integration = await session.scalar(
        select(IntegrationConnection).where(
            IntegrationConnection.tenant_id == principal.tenant_id,
            IntegrationConnection.workspace_id == principal.workspace_id,
            IntegrationConnection.integration_id == "whatsapp",
        )
    )
    if not integration:
        integration = IntegrationConnection(
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            integration_id="whatsapp",
            connected=True,
        )
        session.add(integration)
    else:
        integration.connected = True
        integration.config_encrypted = None
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="integration",
        aggregate_id="whatsapp",
        event_type="integration.connection.changed.v1",
        payload={
            "integrationId": "whatsapp",
            "connected": True,
            "agentId": str(payload.agent_id),
            "phoneNumberId": payload.phone_number_id,
        },
    )
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="That WhatsApp phone number is already connected to another workspace",
        ) from None
    await session.refresh(connection)
    return whatsapp_connection_response(connection)


async def _consume_whatsapp_signup_session(
    signup_session: str,
    *,
    user_id: UUID,
    tenant_id: UUID,
) -> None:
    settings = get_settings()
    try:
        claims = decode_token(signup_session, "whatsapp_signup", settings)
        if UUID(str(claims["sub"])) != user_id or UUID(str(claims["tid"])) != tenant_id:
            raise ValueError("signup session principal mismatch")
        token_id = str(claims["jti"])
    except (ValueError, KeyError, TypeError):
        raise HTTPException(status_code=400, detail="WhatsApp signup session is invalid or expired") from None
    try:
        consumed = await redis_services.client.set(
            f"northstar:whatsapp-signup:{token_id}",
            "consumed",
            ex=settings.meta_signup_session_ttl_seconds,
            nx=True,
        )
    except RedisError:
        if not settings.rate_limit_fail_open:
            raise HTTPException(
                status_code=503,
                detail="Signup session service is temporarily unavailable",
            ) from None
        return
    if not consumed:
        raise HTTPException(status_code=409, detail="WhatsApp signup session was already used")


@router.delete("/whatsapp/{agent_id}", status_code=204)
async def disconnect_whatsapp(agent_id: UUID, principal: IntegrationsManagePrincipal, session: DB) -> None:
    if engine.dialect.name == "postgresql":
        async with engine.connect() as setup_lock_connection:
            async with setup_lock_connection.begin():
                tenant_lock_key = whatsapp_setup_lock_keys(principal.tenant_id, "unused")[0]
                await setup_lock_connection.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                    {"key": tenant_lock_key},
                )
                await _disconnect_whatsapp_locked(agent_id, principal, session, setup_lock_connection)
        return

    async with _local_setup_lock:
        await _disconnect_whatsapp_locked(agent_id, principal, session)


@router.delete("/whatsapp", status_code=204, include_in_schema=False)
async def disconnect_single_whatsapp(principal: IntegrationsManagePrincipal, session: DB) -> None:
    """Compatibility route for clients created before per-bot connections."""

    agent_ids = list(
        await session.scalars(
            select(WhatsAppConnection.agent_id).where(
                WhatsAppConnection.tenant_id == principal.tenant_id,
                WhatsAppConnection.workspace_id == principal.workspace_id,
            )
        )
    )
    if not agent_ids:
        return
    if len(agent_ids) > 1:
        raise HTTPException(
            status_code=409,
            detail="Choose the bot whose WhatsApp number should be disconnected",
        )
    await disconnect_whatsapp(agent_ids[0], principal, session)


async def _disconnect_whatsapp_locked(
    agent_id: UUID,
    principal: AdminPrincipal,
    session: AsyncSession,
    setup_lock_connection: AsyncConnection | None = None,
    *,
    retain: bool = False,
) -> None:
    # The tenant setup lock is already held, so this read is stable against
    # Embedded Signup. Acquire the phone setup lock second, matching /complete.
    connection = await session.scalar(
        select(WhatsAppConnection).where(
            WhatsAppConnection.tenant_id == principal.tenant_id,
            WhatsAppConnection.workspace_id == principal.workspace_id,
            WhatsAppConnection.agent_id == agent_id,
        )
    )
    if not connection:
        return
    if setup_lock_connection is not None:
        phone_lock_key = whatsapp_setup_lock_keys(principal.tenant_id, connection.phone_number_id)[1]
        await setup_lock_connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": phone_lock_key},
        )

    connection = await session.scalar(
        select(WhatsAppConnection)
        .where(
            WhatsAppConnection.id == connection.id,
            WhatsAppConnection.tenant_id == principal.tenant_id,
            WhatsAppConnection.workspace_id == principal.workspace_id,
        )
        .with_for_update()
    )
    if not connection:
        return
    retained_status = connection.status
    connection.status = "disconnecting"
    connection.last_error = None
    await session.commit()

    # Phase two intentionally starts only after the status transition commits
    # and its row lock is released. Workers hold per-thread advisory locks, so
    # this lock order cannot cycle with their final connection updates.
    transient_statuses = ("queued", "failed", "processing")
    inbound_senders = set(
        await session.scalars(
            select(WhatsAppInboundMessage.sender_wa_id).where(
                WhatsAppInboundMessage.connection_id == connection.id,
                WhatsAppInboundMessage.status.in_(transient_statuses),
            )
        )
    )
    outbound_recipients = set(
        await session.scalars(
            select(WhatsAppOutboundDelivery.recipient_wa_id).where(
                WhatsAppOutboundDelivery.connection_id == connection.id,
                WhatsAppOutboundDelivery.status.in_(transient_statuses),
            )
        )
    )
    if setup_lock_connection is not None:
        # Workers hold this same transaction-scoped lock while talking to Meta.
        # Waiting here prevents a send from racing credential deletion.
        for recipient in sorted(inbound_senders | outbound_recipients):
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": whatsapp_thread_lock_key(connection.id, recipient)},
            )

    connection = await session.scalar(
        select(WhatsAppConnection)
        .where(
            WhatsAppConnection.id == connection.id,
            WhatsAppConnection.tenant_id == principal.tenant_id,
            WhatsAppConnection.workspace_id == principal.workspace_id,
        )
        .with_for_update()
    )
    if not connection:
        await session.rollback()
        return

    active_message_ids = select(WhatsAppOutboundDelivery.message_id).where(
        WhatsAppOutboundDelivery.connection_id == connection.id,
        WhatsAppOutboundDelivery.status.in_(transient_statuses),
    )
    await session.execute(
        update(Message)
        .where(
            Message.tenant_id == principal.tenant_id,
            Message.workspace_id == principal.workspace_id,
            Message.id.in_(active_message_ids),
        )
        .values(finish_reason="cancelled")
    )
    affected_conversation_ids = select(WhatsAppInboundMessage.conversation_id).where(
        WhatsAppInboundMessage.connection_id == connection.id,
        WhatsAppInboundMessage.conversation_id.is_not(None),
    )
    observed_sender_ids = select(WhatsAppInboundMessage.sender_wa_id).where(
        WhatsAppInboundMessage.connection_id == connection.id
    )
    disconnected_at = datetime.now(UTC)
    await session.execute(
        update(Conversation)
        .where(
            Conversation.tenant_id == principal.tenant_id,
            Conversation.workspace_id == principal.workspace_id,
            Conversation.agent_id == connection.agent_id,
            Conversation.channel == Channel.WHATSAPP,
            Conversation.state != ConversationState.RESOLVED,
            or_(
                Conversation.id.in_(affected_conversation_ids),
                Conversation.visitor_id.in_(observed_sender_ids),
            ),
        )
        .values(
            state=ConversationState.RESOLVED,
            updated_at=disconnected_at,
            ended_at=disconnected_at,
            resolution="whatsapp_disconnected",
        )
    )
    await session.execute(
        update(WhatsAppOutboundDelivery)
        .where(
            WhatsAppOutboundDelivery.connection_id == connection.id,
            WhatsAppOutboundDelivery.status.in_(transient_statuses),
        )
        .values(
            connection_id=None,
            status="cancelled",
            next_dispatch_at=None,
            last_error="WhatsApp disconnected",
        )
    )
    await session.execute(
        update(WhatsAppInboundMessage)
        .where(
            WhatsAppInboundMessage.connection_id == connection.id,
            WhatsAppInboundMessage.status.in_(transient_statuses),
        )
        .values(
            connection_id=None,
            status="cancelled",
            next_dispatch_at=None,
            last_error="WhatsApp disconnected",
        )
    )
    # Explicitly detach every audit record as well as relying on ON DELETE SET
    # NULL, which also keeps local SQLite/dev deployments deterministic.
    await session.execute(
        update(WhatsAppOutboundDelivery)
        .where(WhatsAppOutboundDelivery.connection_id == connection.id)
        .values(connection_id=None)
    )
    await session.execute(
        update(WhatsAppInboundMessage)
        .where(WhatsAppInboundMessage.connection_id == connection.id)
        .values(connection_id=None)
    )
    # Do not deregister the customer's phone, revoke Facebook permissions, or
    # unsubscribe the whole WABA: those resources may be shared by other phone
    # numbers. Deleting the locally encrypted credential is authoritative. The
    # nullable audit links preserve Meta message-id idempotency across reconnects.
    if retain:
        connection.agent_id = None
        connection.status = retained_status
    else:
        await session.execute(delete(WhatsAppConnection).where(WhatsAppConnection.id == connection.id))
    integration = await session.scalar(
        select(IntegrationConnection).where(
            IntegrationConnection.tenant_id == principal.tenant_id,
            IntegrationConnection.workspace_id == principal.workspace_id,
            IntegrationConnection.integration_id == "whatsapp",
        )
    )
    if integration:
        remaining_connection = await session.scalar(
            select(WhatsAppConnection.id).where(
                WhatsAppConnection.tenant_id == principal.tenant_id,
                WhatsAppConnection.workspace_id == principal.workspace_id,
                WhatsAppConnection.id != connection.id,
                WhatsAppConnection.status == "connected",
            )
        )
        integration.connected = (retain and retained_status == "connected") or remaining_connection is not None
        integration.config_encrypted = None
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="integration",
        aggregate_id="whatsapp",
        event_type="integration.connection.changed.v1",
        payload={
            "integrationId": "whatsapp",
            "connected": bool(integration and integration.connected),
            "agentId": str(agent_id),
            "phoneNumberId": connection.phone_number_id,
        },
    )
    await session.commit()
