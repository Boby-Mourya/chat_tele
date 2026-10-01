from __future__ import annotations

import hmac
from datetime import UTC, datetime
from uuid import UUID

import orjson
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from northstar_api.lead_crm.channel_models import ChannelConnection
from northstar_api.lead_crm.credentials import CredentialStoreError
from northstar_api.routers.channels import DB, ChannelsManagePrincipal
from northstar_api.services import telegram_provisioning as provisioning
from northstar_api.services.rate_limit import redis_services
from northstar_api.services.telegram import TelegramAPIError
from northstar_api.telegram_provisioning import TelegramManagerUpdate, TelegramProvisioning

router = APIRouter(tags=["telegram"])


class StartTelegram(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: UUID = Field(alias="agentId")
    account_id: UUID | None = Field(default=None, alias="accountId")
    connection_id: UUID | None = Field(default=None, alias="connectionId")


@router.post("/channels/telegram/connect/start")
async def start_telegram(payload: StartTelegram, principal: ChannelsManagePrincipal, session: DB):
    rate = await redis_services.check_rate_limit(f"telegram-start:{principal.user_id}", 10, 60)
    if not rate.allowed:
        raise HTTPException(429, "Please wait before connecting Telegram again")
    try:
        if payload.account_id and payload.connection_id:
            raise HTTPException(422, "Choose a new account or an existing connection")
        return await provisioning.start(session, principal, payload.agent_id,
            account_id=payload.account_id, connection_id=payload.connection_id)
    except CredentialStoreError:
        raise HTTPException(503, "Platform credential encryption is not configured") from None
    except TelegramAPIError:
        raise HTTPException(
            503, "Telegram manager is temporarily unavailable. Check its webhook configuration and try again."
        ) from None
    except IntegrityError:
        await session.rollback()
        raise HTTPException(409, "Telegram connection changed concurrently. Please retry.") from None


@router.get("/channels/telegram/provisioning/{session_id}")
async def telegram_status(session_id: UUID, principal: ChannelsManagePrincipal, session: DB):
    value = await session.scalar(
        select(TelegramProvisioning).where(
            TelegramProvisioning.id == session_id,
            TelegramProvisioning.tenant_id == principal.tenant_id,
            TelegramProvisioning.workspace_id == principal.workspace_id,
            TelegramProvisioning.user_id == principal.user_id,
        )
    )
    if not value or (principal.agent_ids is not None and value.agent_id not in principal.agent_ids):
        raise HTTPException(404, "Telegram provisioning session not found")
    connection = await session.get(ChannelConnection, value.connection_id) if value.connection_id else None
    return provisioning.snapshot(value, connection)


@router.post("/webhooks/telegram/manager", include_in_schema=False)
async def manager_webhook(request: Request, session: DB):
    _, _, secret = provisioning.manager_config()
    supplied = request.headers.get("x-telegram-bot-api-secret-token", "")
    if not hmac.compare_digest(secret.encode(), supplied.encode()):
        raise HTTPException(401, "Manager webhook verification failed")
    rate = await redis_services.check_rate_limit("telegram-manager", 300, 60)
    if not rate.allowed:
        raise HTTPException(429, "Manager webhook rate limited")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 65_536:
            raise HTTPException(413, "Manager webhook payload is too large")
    try:
        payload = orjson.loads(body)
    except orjson.JSONDecodeError:
        raise HTTPException(400, "Invalid webhook JSON") from None
    if not isinstance(payload, dict) or type(payload.get("update_id")) is not int:
        raise HTTPException(400, "Invalid Telegram update")
    try:
        async with session.begin_nested():
            session.add(TelegramManagerUpdate(update_id=payload["update_id"], received_at=datetime.now(UTC)))
            await session.flush()
    except IntegrityError:
        return {"acknowledged": True}
    try:
        await provisioning.manager_event(session, payload)
    except TelegramAPIError:
        # Roll back dedup so Telegram can retry a transient send/creation failure.
        raise HTTPException(503, "Telegram management temporarily unavailable") from None
    except IntegrityError:
        await session.rollback()
        raise HTTPException(409, "Telegram provisioning changed concurrently") from None
    await session.commit()
    return {"acknowledged": True}
