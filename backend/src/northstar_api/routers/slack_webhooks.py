from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import orjson
from fastapi import APIRouter, HTTPException, Request, Response

from northstar_api.database import set_tenant_context
from northstar_api.lead_crm.channels import channel_registry
from northstar_api.lead_crm.domain import ChannelProvider
from northstar_api.routers.channels import (
    DB,
    MAX_WEBHOOK_BYTES,
    _context,
    _credentials,
    _external_connection,
    receive_channel_webhook,
)

router = APIRouter(tags=["channels"])


@router.post(
    "/webhooks/channels/{tenant_id}/slack/{public_id}",
    include_in_schema=False,
)
async def receive_slack_webhook(
    tenant_id: UUID,
    public_id: str,
    request: Request,
    session: DB,
) -> Any:
    body = await request.body()
    if len(body) > MAX_WEBHOOK_BYTES:
        raise HTTPException(status_code=413, detail="Webhook payload is too large")
    try:
        payload = orjson.loads(body)
    except orjson.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Webhook payload is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Webhook payload must be an object")

    # Ordinary Slack Events API calls continue through the existing durable
    # provider-neutral webhook path. Request.body() is cached by Starlette, so
    # the downstream route sees the exact bytes used for Slack signature checks.
    if payload.get("type") != "url_verification":
        return await receive_channel_webhook(
            tenant_id=tenant_id,
            provider=ChannelProvider.SLACK,
            public_id=public_id,
            request=request,
            session=session,
        )

    await set_tenant_context(session, tenant_id)
    scoped = await _external_connection(
        session,
        tenant_id=tenant_id,
        provider=ChannelProvider.SLACK,
        public_id=public_id,
    )
    if not scoped:
        raise HTTPException(status_code=404, detail="Channel connection not found")
    connection, _ = scoped
    credentials = _credentials(connection)
    connector = channel_registry.get(ChannelProvider.SLACK)
    headers = {key.lower(): value for key, value in request.headers.items()}
    if not await connector.verify(_context(connection, credentials), headers=headers, body=body):
        connection.last_failure_at = datetime.now(UTC)
        connection.last_error = "Webhook signature/secret verification failed"
        await session.commit()
        raise HTTPException(status_code=401, detail="Webhook verification failed")

    challenge = payload.get("challenge")
    if not isinstance(challenge, str) or not challenge:
        raise HTTPException(status_code=400, detail="Slack URL verification challenge is missing")
    connection.last_event_at = datetime.now(UTC)
    connection.status = "healthy"
    connection.last_error = None
    await session.commit()
    return Response(content=challenge, media_type="text/plain")
