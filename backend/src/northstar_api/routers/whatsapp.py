from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, cast
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import PlainTextResponse
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.config import get_settings
from northstar_api.database import get_session, set_tenant_context
from northstar_api.models import (
    WhatsAppBusinessAccount,
    WhatsAppConnection,
    WhatsAppDeliveryReceipt,
    WhatsAppInboundMessage,
)
from northstar_api.modules.whatsapp.accounts import account_client
from northstar_api.modules.whatsapp.graph import token_expiry_is_current
from northstar_api.workers.tasks import process_whatsapp_inbound

router = APIRouter(prefix="/webhooks/whatsapp", tags=["whatsapp-webhook"])
DB = Annotated[AsyncSession, Depends(get_session)]
logger = structlog.get_logger(__name__)


async def webhook_account(request: Request, session: AsyncSession) -> WhatsAppBusinessAccount | None:
    value = request.path_params.get("account_id")
    if value is None:
        return None
    try:
        account_id = UUID(value)
    except ValueError:
        raise HTTPException(404, "Webhook account not found") from None
    if session.bind and session.bind.dialect.name == "postgresql":
        tenant = await session.scalar(
            text("SELECT northstar_resolve_whatsapp_account(:id)"), {"id": account_id}
        )
        if not tenant:
            raise HTTPException(404, "Webhook account not found")
        await set_tenant_context(session, UUID(str(tenant)))
    account = await session.get(WhatsAppBusinessAccount, account_id)
    if not account:
        raise HTTPException(404, "Webhook account not found")
    return account


@dataclass(frozen=True, slots=True)
class InboundEnvelope:
    phone_number_id: str
    provider_message_id: str
    sender_wa_id: str
    sender_name: str | None
    message_type: str
    message_text: str
    provider_timestamp: datetime | None
    supported: bool


@router.get("")
@router.get("/accounts/{account_id}")
async def verify_whatsapp_webhook(
    request: Request,
    session: DB,
    mode: Annotated[str | None, Query(alias="hub.mode")] = None,
    verify_token: Annotated[str | None, Query(alias="hub.verify_token")] = None,
    challenge: Annotated[str | None, Query(alias="hub.challenge")] = None,
) -> Response:
    account = await webhook_account(request, session)
    settings = account_client(account)[0].settings if account else get_settings()
    configured = settings.meta_whatsapp_webhook_verify_token
    if not configured:
        raise HTTPException(status_code=503, detail="WhatsApp webhook is not configured")
    expected = configured.get_secret_value()
    if (
        mode != "subscribe"
        or challenge is None
        or verify_token is None
        or not hmac.compare_digest(verify_token, expected)
    ):
        raise HTTPException(status_code=403, detail="Webhook verification failed")
    return PlainTextResponse(challenge)


@router.post("")
@router.post("/accounts/{account_id}")
async def receive_whatsapp_webhook(request: Request, session: DB) -> dict[str, str]:
    account = await webhook_account(request, session)
    settings = account_client(account)[0].settings if account else get_settings()
    if (not account and not settings.whatsapp_configured) or not settings.meta_app_secret:
        raise HTTPException(status_code=503, detail="WhatsApp webhook is not configured")
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > settings.meta_webhook_max_bytes:
                raise HTTPException(status_code=413, detail="Webhook payload is too large")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid Content-Length header") from None
    body_chunks: list[bytes] = []
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > settings.meta_webhook_max_bytes:
            raise HTTPException(status_code=413, detail="Webhook payload is too large")
        body_chunks.append(chunk)
    body = b"".join(body_chunks)
    signature = request.headers.get("x-hub-signature-256", "")
    expected_signature = (
        "sha256="
        + hmac.new(
            settings.meta_app_secret.get_secret_value().encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()
    )
    if not signature or not hmac.compare_digest(signature, expected_signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="Webhook body is not valid JSON") from None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Webhook body is not a JSON object")
    if payload.get("object") != "whatsapp_business_account":
        return {"status": "ignored"}

    if account:
        payload["entry"] = (
            [
                entry
                for entry in payload.get("entry", [])
                if isinstance(entry, dict) and entry.get("id") == account.waba_id
            ]
            if isinstance(payload.get("entry"), list)
            else []
        )
    account_id = account.id if account else None
    await receive_delivery_statuses(session, payload, account_id)
    inbound = extract_inbound_messages(payload)
    dispatch_ids: list[tuple[UUID, UUID]] = []
    for item in inbound:
        connection = await _resolve_connection(session, item.phone_number_id)
        if not connection or connection.business_account_id != account_id:
            # ACK events for numbers that are no longer connected. Returning an
            # error would make Meta retry forever after a deliberate disconnect.
            logger.info(
                "whatsapp_webhook_number_not_connected",
                phone_number_id=item.phone_number_id,
            )
            continue
        receipt = await _durably_receive(session, connection, item)
        if receipt is None:
            # Provider message ids are globally assigned. A preserved receipt
            # from a prior workspace/connection proves this signed event was
            # already durably handled, without exposing its former tenant.
            continue
        retry_due = receipt.next_dispatch_at is None
        if receipt.next_dispatch_at is not None:
            next_dispatch_at = receipt.next_dispatch_at
            if next_dispatch_at.tzinfo is None:
                next_dispatch_at = next_dispatch_at.replace(tzinfo=UTC)
            retry_due = next_dispatch_at <= datetime.now(UTC)
        if (
            item.supported
            and receipt.status in {"queued", "failed"}
            and (receipt.dispatched_at is None or retry_due)
            and receipt.dispatch_attempts < settings.whatsapp_dispatch_max_attempts
        ):
            dispatch_ids.append((receipt.id, receipt.tenant_id))
        elif (
            receipt.status in {"queued", "failed"}
            and receipt.dispatch_attempts >= settings.whatsapp_dispatch_max_attempts
            and (receipt.dispatched_at is None or retry_due)
        ):
            receipt.status = "dispatch_failed"
            receipt.next_dispatch_at = None
            await session.commit()

    for receipt_id, tenant_id in dict.fromkeys(dispatch_ids):
        try:
            await asyncio.to_thread(
                process_whatsapp_inbound.apply_async,
                args=[str(receipt_id)],
                queue="whatsapp.inbound",
                routing_key="whatsapp.inbound",
            )
        except Exception:
            await _mark_dispatch_failure(session, receipt_id, tenant_id)
            # The receipt is already committed. A 503 tells Meta to retry, at
            # which point the same provider message id is safely re-published.
            raise HTTPException(
                status_code=503,
                detail="Inbound message was saved but queue dispatch is temporarily unavailable",
            ) from None
        await _mark_dispatched(session, receipt_id, tenant_id)
    return {"status": "accepted"}


async def _resolve_connection(session: AsyncSession, phone_number_id: str) -> WhatsAppConnection | None:
    if session.bind and session.bind.dialect.name == "postgresql":
        tenant_id_raw = await session.scalar(
            text("SELECT northstar_resolve_whatsapp_tenant(:phone_number_id)"),
            {"phone_number_id": phone_number_id},
        )
        if tenant_id_raw is None:
            await session.rollback()
            return None
        tenant_id = UUID(str(tenant_id_raw))
        await set_tenant_context(session, tenant_id)
        connection = cast(
            WhatsAppConnection | None,
            await session.scalar(
                select(WhatsAppConnection).where(
                    WhatsAppConnection.tenant_id == tenant_id,
                    WhatsAppConnection.phone_number_id == phone_number_id,
                    WhatsAppConnection.status == "connected",
                )
            ),
        )
    else:
        connection = cast(
            WhatsAppConnection | None,
            await session.scalar(
                select(WhatsAppConnection).where(
                    WhatsAppConnection.phone_number_id == phone_number_id,
                    WhatsAppConnection.status == "connected",
                )
            ),
        )
    if connection and not token_expiry_is_current(connection.token_expires_at):
        return None
    return connection


async def _durably_receive(
    session: AsyncSession,
    connection: WhatsAppConnection,
    item: InboundEnvelope,
) -> WhatsAppInboundMessage | None:
    tenant_id = connection.tenant_id
    connection_id = connection.id
    phone_number_id = connection.phone_number_id
    existing = await session.scalar(
        select(WhatsAppInboundMessage).where(
            WhatsAppInboundMessage.provider_message_id == item.provider_message_id,
            WhatsAppInboundMessage.tenant_id == tenant_id,
        )
    )
    if existing:
        await session.commit()
        return existing
    receipt = WhatsAppInboundMessage(
        tenant_id=tenant_id,
        workspace_id=connection.workspace_id,
        connection_id=connection_id,
        phone_number_id=phone_number_id,
        provider_message_id=item.provider_message_id,
        sender_wa_id=item.sender_wa_id,
        sender_name=item.sender_name,
        message_type=item.message_type,
        message_text=item.message_text,
        provider_timestamp=item.provider_timestamp,
        status="queued" if item.supported and connection.agent_id else "ignored",
        last_error="No bot is deployed to this number" if connection.agent_id is None else None,
    )
    session.add(receipt)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        await set_tenant_context(session, tenant_id)
        existing = await session.scalar(
            select(WhatsAppInboundMessage).where(
                WhatsAppInboundMessage.provider_message_id == item.provider_message_id,
                WhatsAppInboundMessage.tenant_id == tenant_id,
            )
        )
        if not existing:
            if session.bind and session.bind.dialect.name == "postgresql":
                globally_seen = bool(
                    await session.scalar(
                        text("SELECT northstar_whatsapp_provider_message_seen(:provider_id)"),
                        {"provider_id": item.provider_message_id},
                    )
                )
            else:
                globally_seen = bool(
                    await session.scalar(
                        select(WhatsAppInboundMessage.id)
                        .where(WhatsAppInboundMessage.provider_message_id == item.provider_message_id)
                        .limit(1)
                    )
                )
            if globally_seen:
                logger.info("whatsapp_webhook_global_duplicate_suppressed")
                return None
            raise
        return cast(WhatsAppInboundMessage, existing)
    await session.refresh(receipt)
    return receipt


async def _mark_dispatched(session: AsyncSession, receipt_id: UUID, tenant_id: UUID) -> None:
    await set_tenant_context(session, tenant_id)
    receipt = await session.scalar(select(WhatsAppInboundMessage).where(
        WhatsAppInboundMessage.id == receipt_id, WhatsAppInboundMessage.tenant_id == tenant_id,
    ).with_for_update().execution_options(populate_existing=True))
    if not receipt or receipt.status not in {"queued", "failed"}:
        await session.rollback()
        return
    receipt.status = "queued"
    receipt.dispatch_attempts += 1
    receipt.dispatched_at = datetime.now(UTC)
    receipt.next_dispatch_at = datetime.now(UTC) + timedelta(minutes=5)
    receipt.last_error = None
    await session.commit()


async def _mark_dispatch_failure(session: AsyncSession, receipt_id: UUID, tenant_id: UUID) -> None:
    await set_tenant_context(session, tenant_id)
    receipt = await session.scalar(select(WhatsAppInboundMessage).where(
        WhatsAppInboundMessage.id == receipt_id, WhatsAppInboundMessage.tenant_id == tenant_id,
    ).with_for_update().execution_options(populate_existing=True))
    if not receipt or receipt.status not in {"queued", "failed"}:
        await session.rollback()
        return
    receipt.status = "failed"
    receipt.dispatch_attempts += 1
    receipt.last_error = "queue dispatch unavailable"
    if receipt.dispatch_attempts >= get_settings().whatsapp_dispatch_max_attempts:
        receipt.status = "dispatch_failed"
        receipt.next_dispatch_at = None
    await session.commit()


async def receive_delivery_statuses(
    session: AsyncSession, payload: dict[str, Any], account_id: UUID | None = None
) -> None:
    """Persist each transition once; late 'sent' events cannot erase 'read' evidence."""
    entries = payload.get("entry")
    for entry in entries if isinstance(entries, list) else []:
        changes = entry.get("changes") if isinstance(entry, dict) else None
        for change in changes if isinstance(changes, list) else []:
            if not isinstance(change, dict) or change.get("field") != "messages":
                continue
            value = change.get("value")
            if not isinstance(value, dict):
                continue
            metadata = value.get("metadata")
            phone_id = metadata.get("phone_number_id") if isinstance(metadata, dict) else None
            if not _valid_numeric_id(phone_id):
                continue
            statuses = value.get("statuses")
            for item in statuses if isinstance(statuses, list) else []:
                if not isinstance(item, dict):
                    continue
                provider_id, status = item.get("id"), item.get("status")
                timestamp = _provider_timestamp(item.get("timestamp"))
                if (
                    not isinstance(provider_id, str)
                    or not 1 <= len(provider_id) <= 160
                    or not isinstance(status, str)
                    or status not in {"sent", "delivered", "read", "failed"}
                    or timestamp is None
                ):
                    continue
                connection = await _resolve_connection(session, cast(str, phone_id))
                if connection is None or connection.business_account_id != account_id:
                    continue
                errors = item.get("errors")
                code = (
                    errors[0].get("code")
                    if isinstance(errors, list) and errors and isinstance(errors[0], dict)
                    else None
                )
                receipt = WhatsAppDeliveryReceipt(
                    tenant_id=connection.tenant_id,
                    workspace_id=connection.workspace_id,
                    connection_id=connection.id,
                    provider_message_id=provider_id,
                    status=status,
                    provider_timestamp=timestamp,
                    error_code=str(code)[:40] if isinstance(code, int) else None,
                )
                # A savepoint suppresses duplicate retries without losing other receipts.
                try:
                    async with session.begin_nested():
                        session.add(receipt)
                        await session.flush()
                except IntegrityError:
                    pass
                await session.commit()


def extract_inbound_messages(payload: dict[str, Any]) -> list[InboundEnvelope]:
    result: list[InboundEnvelope] = []
    entries = payload.get("entry")
    if not isinstance(entries, list):
        return result
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        changes = entry.get("changes")
        if not isinstance(changes, list):
            continue
        for change in changes:
            if not isinstance(change, dict) or change.get("field") != "messages":
                continue
            value = change.get("value")
            if not isinstance(value, dict):
                continue
            metadata = value.get("metadata")
            phone_number_id = metadata.get("phone_number_id") if isinstance(metadata, dict) else None
            if not _valid_numeric_id(phone_number_id):
                continue
            valid_phone_number_id = cast(str, phone_number_id)
            contact_names = _contact_names(value.get("contacts"))
            messages = value.get("messages")
            if not isinstance(messages, list):
                continue
            for message in messages:
                if not isinstance(message, dict):
                    continue
                provider_id = message.get("id")
                sender = message.get("from")
                message_type = message.get("type")
                if (
                    not isinstance(provider_id, str)
                    or not provider_id
                    or len(provider_id) > 160
                    or not _valid_numeric_id(sender)
                    or not isinstance(message_type, str)
                    or len(message_type) > 40
                ):
                    continue
                valid_sender = cast(str, sender)
                message_text = _message_text(message, message_type)
                supported = message_text is not None
                result.append(
                    InboundEnvelope(
                        phone_number_id=valid_phone_number_id,
                        provider_message_id=provider_id,
                        sender_wa_id=valid_sender,
                        sender_name=contact_names.get(valid_sender),
                        message_type=message_type,
                        message_text=(message_text or "")[:12_000],
                        provider_timestamp=_provider_timestamp(message.get("timestamp")),
                        supported=supported,
                    )
                )
    return result


def _contact_names(value: object) -> dict[str, str]:
    contacts: dict[str, str] = {}
    if not isinstance(value, list):
        return contacts
    for contact in value:
        if not isinstance(contact, dict) or not _valid_numeric_id(contact.get("wa_id")):
            continue
        profile = contact.get("profile")
        name = profile.get("name") if isinstance(profile, dict) else None
        if isinstance(name, str) and name.strip():
            contacts[contact["wa_id"]] = name.strip()[:160]
    return contacts


def _message_text(message: dict[str, Any], message_type: str) -> str | None:
    if message_type == "text":
        body = message.get("text")
        value = body.get("body") if isinstance(body, dict) else None
    elif message_type == "button":
        body = message.get("button")
        value = body.get("text") if isinstance(body, dict) else None
    elif message_type == "interactive":
        interactive = message.get("interactive")
        interactive_type = interactive.get("type") if isinstance(interactive, dict) else None
        selection = (
            interactive.get(interactive_type)
            if isinstance(interactive, dict) and isinstance(interactive_type, str)
            else None
        )
        value = selection.get("title") if isinstance(selection, dict) else None
    else:
        return None
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _provider_timestamp(value: object) -> datetime | None:
    if not isinstance(value, (str, int)):
        return None
    try:
        timestamp = int(value)
        parsed = datetime.fromtimestamp(timestamp, tz=UTC)
    except (TypeError, ValueError, OSError, OverflowError):
        return None
    # Reject implausible values rather than persisting a date near year 1/9999.
    if parsed.year < 2000 or parsed.year > 2200:
        return None
    return parsed


def _valid_numeric_id(value: object) -> bool:
    return isinstance(value, str) and value.isdigit() and 1 <= len(value) <= 80
