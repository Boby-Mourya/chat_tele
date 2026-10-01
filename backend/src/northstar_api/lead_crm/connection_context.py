from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.lead_crm.connectors import CRMConnectionContext, CRMError, crm_registry
from northstar_api.lead_crm.credentials import CredentialStoreError, credential_store
from northstar_api.lead_crm.domain import CRMProvider, NormalizedCRMErrorCode
from northstar_api.lead_crm.models import CRMConnection


async def load_connection_context(
    session: AsyncSession, *, tenant_id: UUID, connection_id: UUID
) -> tuple[CRMConnection, CRMConnectionContext]:
    """Serialize credential refresh and connection disable with provider calls.

    The caller owns the transaction and must commit refreshed encrypted tokens.
    The connection lock is retained until the caller commits or rolls back.
    """
    connection = await session.scalar(
        select(CRMConnection)
        .where(CRMConnection.id == connection_id, CRMConnection.tenant_id == tenant_id)
        .with_for_update()
    )
    if connection is None or connection.status == "disabled":
        raise CRMError(NormalizedCRMErrorCode.CONFIGURATION_ERROR, "CRM connection is unavailable")
    credentials: dict[str, Any] = {}
    if connection.credentials_encrypted:
        try:
            credentials = credential_store.decrypt(connection.credentials_encrypted)
        except CredentialStoreError as exc:
            raise CRMError(
                NormalizedCRMErrorCode.AUTHENTICATION_ERROR,
                "Stored CRM credentials are unreadable",
                requires_reconnect=True,
            ) from exc
    provider = CRMProvider(connection.provider)
    context = CRMConnectionContext(
        tenant_id=tenant_id,
        connection_id=connection_id,
        provider=provider,
        configuration=dict(connection.configuration_json or {}),
        credentials=credentials,
    )
    connector = crm_registry.get(provider)
    if connector.capabilities.oauth:
        try:
            expires_at = int(credentials.get("access_token_expires_at") or 0)
        except (ValueError, TypeError) as exc:
            raise CRMError(
                NormalizedCRMErrorCode.AUTHENTICATION_ERROR,
                "Stored token expiry is invalid",
                requires_reconnect=True,
            ) from exc
        if not credentials.get("access_token") or (expires_at and expires_at <= int(time.time()) + 120):
            refreshed = await connector.refresh_credentials(context)
            if not isinstance(refreshed.get("access_token"), str) or not refreshed["access_token"]:
                raise CRMError(
                    NormalizedCRMErrorCode.AUTHENTICATION_ERROR,
                    "Token refresh returned no access token",
                    requires_reconnect=True,
                )
            credentials.update(refreshed)
            connection.credentials_encrypted = credential_store.encrypt(credentials)
            connection.last_authenticated_at = datetime.now(UTC)
            context = CRMConnectionContext(
                tenant_id=tenant_id,
                connection_id=connection_id,
                provider=provider,
                configuration=context.configuration,
                credentials=credentials,
            )
    return connection, context
