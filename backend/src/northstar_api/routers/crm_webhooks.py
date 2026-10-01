from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

import orjson
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import get_session, set_tenant_context
from northstar_api.lead_crm.credentials import CredentialStoreError, credential_store
from northstar_api.lead_crm.models import CRMConnection, CRMWebhookEvent
from northstar_api.lead_crm.workspace_scope import WorkspaceCRMConnection
from northstar_api.services.outbox import enqueue_event

router = APIRouter(tags=["crm-webhooks"])
DB = Annotated[AsyncSession, Depends(get_session)]
MAX_BODY_BYTES = 1_048_576


def _extract(value: Any, path: str) -> Any:
    current = value
    for part in path.removeprefix("$.").split("."):
        if not part:
            continue
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            current = current[index] if index < len(current) else None
        else:
            return None
    return current


def _credentials(connection: CRMConnection) -> dict[str, Any]:
    if not connection.credentials_encrypted:
        return {}
    try:
        return credential_store.decrypt(connection.credentials_encrypted)
    except CredentialStoreError as exc:
        raise HTTPException(status_code=409, detail="CRM webhook credentials require reconnection") from exc


def _webhook_config(connection: CRMConnection) -> dict[str, Any]:
    config = dict(connection.configuration_json or {})
    value = config.get("inboundWebhook")
    return dict(value) if isinstance(value, dict) else {}


def _verify(
    connection: CRMConnection, credentials: dict[str, Any], headers: dict[str, str], body: bytes
) -> bool:
    webhook = _webhook_config(connection)
    mode = str(webhook.get("verification") or "HMAC_SHA256").upper()
    if mode == "NONE":
        return bool(webhook.get("allowUnsigned", False))
    if mode == "BEARER":
        expected = str(credentials.get("webhook_token") or "")
        supplied = headers.get("authorization", "")
        return bool(expected and supplied.startswith("Bearer ") and hmac.compare_digest(expected, supplied[7:]))
    if mode == "HEADER_TOKEN":
        header = str(webhook.get("header") or "x-webhook-token").lower()
        expected = str(credentials.get("webhook_token") or "")
        supplied = headers.get(header, "")
        return bool(expected and supplied and hmac.compare_digest(expected, supplied))
    header = str(webhook.get("signatureHeader") or "x-webhook-signature").lower()
    prefix = str(webhook.get("signaturePrefix") or "sha256=")
    secret = str(credentials.get("webhook_secret") or "")
    supplied = headers.get(header, "")
    expected = prefix + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return bool(secret and supplied and hmac.compare_digest(expected, supplied))


@router.post("/webhooks/crm/{tenant_id}/{provider}/{public_id}", include_in_schema=False)
async def receive_crm_webhook(
    tenant_id: uuid.UUID,
    provider: str,
    public_id: str,
    request: Request,
    session: DB,
) -> dict[str, Any]:
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Webhook payload is too large")
    try:
        payload = orjson.loads(body)
    except orjson.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Webhook payload is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Webhook payload must be an object")

    await set_tenant_context(session, tenant_id)
    row = (
        await session.execute(
            select(CRMConnection, WorkspaceCRMConnection)
            .join(WorkspaceCRMConnection, WorkspaceCRMConnection.connection_id == CRMConnection.id)
            .where(
                CRMConnection.tenant_id == tenant_id,
                CRMConnection.public_id == public_id,
                CRMConnection.provider == provider,
                CRMConnection.status != "disabled",
                WorkspaceCRMConnection.tenant_id == tenant_id,
            )
        )
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="CRM connection not found")
    connection, workspace_scope = row
    credentials = _credentials(connection)
    headers = {key.lower(): value for key, value in request.headers.items()}
    if not _verify(connection, credentials, headers, body):
        connection.last_failure_at = datetime.now(UTC)
        connection.last_error = "CRM webhook verification failed"
        await session.commit()
        raise HTTPException(status_code=401, detail="CRM webhook verification failed")

    webhook_config = _webhook_config(connection)
    event_id = _extract(payload, str(webhook_config.get("eventIdPath") or "$.eventId"))
    if event_id is None:
        event_id = hashlib.sha256(body).hexdigest()
    event_type = _extract(payload, str(webhook_config.get("eventTypePath") or "$.eventType"))
    correlation_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    existing = await session.scalar(
        select(CRMWebhookEvent.id).where(
            CRMWebhookEvent.tenant_id == tenant_id,
            CRMWebhookEvent.connection_id == connection.id,
            CRMWebhookEvent.external_event_id == str(event_id),
        )
    )
    if existing:
        return {
            "acknowledged": True,
            "duplicate": True,
            "correlationId": correlation_id,
            "workspaceId": str(workspace_scope.workspace_id),
        }

    value = CRMWebhookEvent(
        tenant_id=tenant_id,
        connection_id=connection.id,
        provider=provider,
        external_event_id=str(event_id)[:512],
        event_type=str(event_type or "record.changed")[:160],
        verification_status="verified",
        processing_status="received",
        payload_hash=hashlib.sha256(body).hexdigest(),
        payload_json=payload,
        correlation_id=correlation_id,
        received_at=datetime.now(UTC),
    )
    try:
        async with session.begin_nested():
            session.add(value)
            await session.flush()
    except IntegrityError:
        return {
            "acknowledged": True,
            "duplicate": True,
            "correlationId": correlation_id,
            "workspaceId": str(workspace_scope.workspace_id),
        }
    enqueue_event(
        session,
        tenant_id=tenant_id,
        aggregate_type="crm_webhook_event",
        aggregate_id=value.id,
        event_type="crm.webhook.received.v1",
        payload={
            "webhookEventId": str(value.id),
            "workspaceId": str(workspace_scope.workspace_id),
            "connectionId": str(connection.id),
            "provider": provider,
        },
    )
    connection.last_success_at = datetime.now(UTC)
    connection.last_error = None
    await session.commit()
    return {
        "acknowledged": True,
        "duplicate": False,
        "correlationId": correlation_id,
        "workspaceId": str(workspace_scope.workspace_id),
    }
