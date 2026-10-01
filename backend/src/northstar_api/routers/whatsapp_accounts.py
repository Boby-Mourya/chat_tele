from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field, SecretStr
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from northstar_api.config import get_settings
from northstar_api.database import engine
from northstar_api.lead_crm.credentials import CredentialStoreError, credential_store
from northstar_api.models import Agent, AgentStatus, WhatsAppBusinessAccount, WhatsAppConnection
from northstar_api.modules.whatsapp.accounts import account_client
from northstar_api.modules.whatsapp.graph import WhatsAppGraphError, token_expiry_is_current
from northstar_api.routers.integrations import (
    DB,
    IntegrationsManagePrincipal,
    IntegrationsViewPrincipal,
    _disconnect_whatsapp_locked,
    _local_setup_lock,
    whatsapp_connection_response,
)
from northstar_api.schemas import APIModel, WhatsAppConnectionOut

router = APIRouter(prefix="/integrations/whatsapp-accounts", tags=["whatsapp-accounts"])


class AccountInput(APIModel):
    name: str = Field(min_length=1, max_length=160)
    waba_id: str = Field(pattern=r"^[0-9]{1,80}$")
    app_id: str = Field(pattern=r"^[0-9]{1,80}$")
    app_secret: SecretStr = Field(min_length=8, max_length=4096)
    access_token: SecretStr = Field(min_length=8, max_length=8192)
    verify_token: SecretStr = Field(min_length=32, max_length=256)


class NumberInput(APIModel):
    phone_number_id: str = Field(pattern=r"^[0-9]{1,80}$")
    pin: SecretStr = Field(min_length=6, max_length=6)


class AssignmentInput(APIModel):
    agent_id: UUID | None = None


def account_out(account, request):
    base = (get_settings().crm_oauth_public_base_url or str(request.base_url)).rstrip("/")
    return {
        "id": str(account.id),
        "name": account.name,
        "wabaId": account.waba_id,
        "appId": account.app_id,
        "status": account.status,
        "webhookUrl": f"{base}/api/v1/webhooks/whatsapp/accounts/{account.id}",
    }


async def owned_account(session, principal, account_id):
    account = await session.scalar(
        select(WhatsAppBusinessAccount).where(
            WhatsAppBusinessAccount.id == account_id,
            WhatsAppBusinessAccount.tenant_id == principal.tenant_id,
            WhatsAppBusinessAccount.workspace_id == principal.workspace_id,
        )
    )
    if not account:
        raise HTTPException(404, "WhatsApp account not found")
    return account


@asynccontextmanager
async def setup_lock(principal):
    if engine.dialect.name == "postgresql":
        async with engine.connect() as connection:
            async with connection.begin():
                await connection.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                    {"key": f"whatsapp-setup:tenant:{principal.tenant_id}"},
                )
                yield connection
    else:
        async with _local_setup_lock:
            yield None


@router.get("")
async def list_accounts(principal: IntegrationsViewPrincipal, session: DB, request: Request):
    accounts = await session.scalars(
        select(WhatsAppBusinessAccount)
        .where(
            WhatsAppBusinessAccount.tenant_id == principal.tenant_id,
            WhatsAppBusinessAccount.workspace_id == principal.workspace_id,
        )
        .order_by(WhatsAppBusinessAccount.created_at)
    )
    return [account_out(account, request) for account in accounts]


@router.post("", status_code=201)
async def create_account(
    payload: AccountInput, principal: IntegrationsManagePrincipal, session: DB, request: Request
):
    async with setup_lock(principal):
        try:
            encrypted = credential_store.encrypt(
                {
                    "app_secret": payload.app_secret.get_secret_value(),
                    "access_token": payload.access_token.get_secret_value(),
                    "verify_token": payload.verify_token.get_secret_value(),
                }
            )
        except CredentialStoreError:
            raise HTTPException(
                503,
                "The deployment owner must configure CRM_CREDENTIAL_ENCRYPTION_KEY before saving account credentials",
            ) from None
        account = WhatsAppBusinessAccount(
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            name=payload.name.strip(),
            app_id=payload.app_id,
            waba_id=payload.waba_id,
            credentials_encrypted=encrypted,
        )
        client, token = account_client(account)
        try:
            await client.validate_token(token)
            # Verify WABA access before saving any customer credentials.
            await client._request(
                "GET",
                f"{account.waba_id}/phone_numbers",
                operation="business account validation",
                access_token=token,
                params={"fields": "id", "limit": "1"},
            )
        except WhatsAppGraphError:
            raise HTTPException(
                502, "Meta could not verify this app, access token, permissions or business account"
            ) from None
        session.add(account)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            raise HTTPException(
                409, "This WhatsApp Business Account is already saved; select it to add another number"
            ) from None
        return account_out(account, request)


@router.get("/{account_id}/numbers")
async def discover_numbers(account_id: UUID, principal: IntegrationsManagePrincipal, session: DB):
    account = await owned_account(session, principal, account_id)
    client, token = account_client(account)
    rows = []
    after = None
    try:
        for _ in range(10):
            params = {"fields": "id,display_phone_number,verified_name", "limit": "100"}
            if after:
                params["after"] = after
            data = await client._request(
                "GET",
                f"{account.waba_id}/phone_numbers",
                operation="phone number lookup",
                access_token=token,
                params=params,
            )
            rows.extend(data.get("data", []))
            paging = data.get("paging", {})
            cursor = paging.get("cursors", {}).get("after")
            if not paging.get("next") or not cursor or cursor == after:
                break
            after = cursor
    except WhatsAppGraphError:
        raise HTTPException(
            502, "Meta could not load this account's numbers; check the account token and permissions"
        ) from None
    return [
        {
            "id": str(row["id"]),
            "displayPhoneNumber": row.get("display_phone_number", ""),
            "verifiedName": row.get("verified_name", ""),
        }
        for row in rows
    ]


@router.put("/{account_id}")
async def update_account(
    account_id: UUID,
    payload: AccountInput,
    principal: IntegrationsManagePrincipal,
    session: DB,
    request: Request,
):
    async with setup_lock(principal):
        account = await owned_account(session, principal, account_id)
        if payload.waba_id != account.waba_id or payload.app_id != account.app_id:
            raise HTTPException(409, "Use Add account for a different Meta app or business account")
        try:
            encrypted = credential_store.encrypt(
                {
                    "app_secret": payload.app_secret.get_secret_value(),
                    "access_token": payload.access_token.get_secret_value(),
                    "verify_token": payload.verify_token.get_secret_value(),
                }
            )
            candidate = WhatsAppBusinessAccount(app_id=account.app_id, credentials_encrypted=encrypted)
            client, token = account_client(candidate)
            expiry = await client.validate_token(token)
            await client._request(
                "GET",
                f"{account.waba_id}/phone_numbers",
                operation="business account validation",
                access_token=token,
                params={"fields": "id", "limit": "1"},
            )
        except CredentialStoreError:
            raise HTTPException(
                503, "Account encryption is unavailable; ask the deployment owner to check the encryption key"
            ) from None
        except WhatsAppGraphError:
            raise HTTPException(
                502, "Meta could not verify the replacement credentials; the existing account was not changed"
            ) from None
        account.credentials_encrypted = encrypted
        account.name = payload.name.strip()
        account.status = "needs_webhook"
        await session.execute(
            update(WhatsAppConnection)
            .where(WhatsAppConnection.business_account_id == account.id)
            .values(token_expires_at=expiry, status="needs_webhook")
        )
        await session.commit()
        return account_out(account, request)


@router.post("/{account_id}/webhook")
async def connect_webhook(
    account_id: UUID, principal: IntegrationsManagePrincipal, session: DB, request: Request
):
    async with setup_lock(principal):
        account = await owned_account(session, principal, account_id)
        callback = account_out(account, request)["webhookUrl"]
        if not callback.startswith("https://"):
            raise HTTPException(
                409, "Account saved. Start ngrok with a public HTTPS URL before activating the webhook"
            )
        client, token = account_client(account)
        try:
            await client.subscribe_app(token, waba_id=account.waba_id)
            await client._request(
                "POST",
                f"{account.waba_id}/subscribed_apps",
                operation="account webhook configuration",
                access_token=token,
                json={
                    "override_callback_uri": callback,
                    "verify_token": client.settings.meta_whatsapp_webhook_verify_token.get_secret_value(),
                },
            )
        except WhatsAppGraphError:
            raise HTTPException(
                502,
                "Meta could not activate the webhook. Configure the app's WhatsApp messages subscription and verify that the displayed HTTPS callback is reachable",
            ) from None
        account.status = "connected"
        await session.execute(
            update(WhatsAppConnection)
            .where(
                WhatsAppConnection.business_account_id == account.id,
                WhatsAppConnection.status == "needs_webhook",
            )
            .values(status="connected")
        )
        await session.commit()
        return account_out(account, request)


@router.post("/{account_id}/numbers", response_model=WhatsAppConnectionOut, status_code=201)
async def add_number(
    account_id: UUID, payload: NumberInput, principal: IntegrationsManagePrincipal, session: DB
):
    if not payload.pin.get_secret_value().isdigit():
        raise HTTPException(422, "The registration PIN must contain six digits")
    async with setup_lock(principal) as lock_connection:
        if lock_connection is not None:
            await lock_connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"whatsapp-setup:phone:{payload.phone_number_id}"},
            )
        account = await owned_account(session, principal, account_id)
        existing = await session.scalar(
            select(WhatsAppConnection).where(WhatsAppConnection.phone_number_id == payload.phone_number_id)
        )
        if existing:
            raise HTTPException(409, "This number is already saved")
        if engine.dialect.name == "postgresql":
            owner = await session.scalar(
                text("SELECT northstar_find_whatsapp_phone_owner(:phone)"), {"phone": payload.phone_number_id}
            )
            if owner:
                raise HTTPException(409, "This number is already saved")
        client, token = account_client(account)
        try:
            expiry = await client.validate_token(token)
            number, name = await client.get_phone_for_waba(
                token, waba_id=account.waba_id, phone_number_id=payload.phone_number_id
            )
            await client.register_phone(
                token, phone_number_id=payload.phone_number_id, pin=payload.pin.get_secret_value()
            )
        except WhatsAppGraphError:
            raise HTTPException(
                502,
                "Meta could not register this number. Check account ownership, number verification and its six-digit PIN",
            ) from None
        connection = WhatsAppConnection(
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            business_account_id=account.id,
            agent_id=None,
            waba_id=account.waba_id,
            phone_number_id=payload.phone_number_id,
            display_phone_number=number,
            verified_name=name,
            access_token_encrypted=b"",
            token_expires_at=expiry,
            status="connected" if account.status == "connected" else "needs_webhook",
            connected_at=datetime.now(UTC),
        )
        session.add(connection)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            raise HTTPException(409, "This number is already saved") from None
        return whatsapp_connection_response(connection)


@router.put("/numbers/{connection_id}/assignment", response_model=WhatsAppConnectionOut)
async def assign_number(
    connection_id: UUID, payload: AssignmentInput, principal: IntegrationsManagePrincipal, session: DB
):
    async with setup_lock(principal) as lock_connection:
        connection = await session.scalar(
            select(WhatsAppConnection).where(
                WhatsAppConnection.id == connection_id,
                WhatsAppConnection.tenant_id == principal.tenant_id,
                WhatsAppConnection.workspace_id == principal.workspace_id,
            )
        )
        if not connection:
            raise HTTPException(404, "WhatsApp number not found")
        if payload.agent_id:
            agent = await session.scalar(
                select(Agent).where(
                    Agent.id == payload.agent_id,
                    Agent.tenant_id == principal.tenant_id,
                    Agent.workspace_id == principal.workspace_id,
                    Agent.deleted_at.is_(None),
                )
            )
            if not agent or agent.status not in {AgentStatus.ACTIVE, AgentStatus.DRAFT}:
                raise HTTPException(409, "Select an active or draft bot in this workspace")
            if connection.status != "connected" or not token_expiry_is_current(connection.token_expires_at):
                raise HTTPException(409, "Activate this account's webhook before deploying its number")
            current = await session.scalar(
                select(WhatsAppConnection).where(
                    WhatsAppConnection.workspace_id == principal.workspace_id,
                    WhatsAppConnection.agent_id == payload.agent_id,
                    WhatsAppConnection.id != connection.id,
                )
            )
            if current:
                await _disconnect_whatsapp_locked(
                    current.agent_id, principal, session, lock_connection, retain=True
                )
        if connection.agent_id != payload.agent_id:
            if connection.agent_id:
                await _disconnect_whatsapp_locked(
                    connection.agent_id, principal, session, lock_connection, retain=True
                )
            connection.agent_id = payload.agent_id
            await session.commit()
        return whatsapp_connection_response(connection)
