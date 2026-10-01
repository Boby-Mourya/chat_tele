from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlencode

from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import set_tenant_context
from northstar_api.lead_crm.audit import record_integration_audit
from northstar_api.lead_crm.connectors import CRMConnectionContext, CRMError, crm_registry
from northstar_api.lead_crm.credentials import CredentialStoreError, credential_store
from northstar_api.lead_crm.domain import CRMConnectionStatus, CRMProvider
from northstar_api.lead_crm.models import CRMConnection
from northstar_api.lead_crm.oauth import OAuthStateError, oauth_state_store
from northstar_api.lead_crm.workspace_scope import WorkspaceCRMConnection
from northstar_api.services.zoho_one_click import (
    ZohoOneClickError,
    bootstrap_zoho_connection,
    normalized_failure_status,
)
from northstar_api.services.zoho_one_click_common import decrypt_zoho_credentials
from northstar_api.zoho_platform import (
    ZohoPlatformConfiguration,
    ZohoPlatformConfigurationError,
    resolve_zoho_data_center,
)


def redirect_target(base_url: str, **params: str | None) -> str:
    safe = {key: value for key, value in params.items() if value not in {None, ""}}
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}{urlencode(safe)}"


async def process_zoho_one_click_callback(
    session: AsyncSession,
    *,
    state: str,
    code: str | None,
    error: str | None,
    location: str | None,
    accounts_server: str | None,
    platform: ZohoPlatformConfiguration | None,
) -> RedirectResponse:
    frontend_url = (
        platform.frontend_return_url
        if platform is not None
        else "http://localhost:3100/integrations"
    )
    try:
        saved = await oauth_state_store.consume(state)
    except OAuthStateError:
        return RedirectResponse(
            redirect_target(
                frontend_url,
                crm="failed",
                provider="zoho",
                reason="invalid_or_expired_state",
            ),
            status_code=303,
        )
    if saved.provider != CRMProvider.ZOHO.value:
        return RedirectResponse(
            redirect_target(
                frontend_url,
                crm="failed",
                provider="zoho",
                reason="provider_mismatch",
            ),
            status_code=303,
        )

    await set_tenant_context(session, saved.tenant_id)
    row = (
        await session.execute(
            select(CRMConnection, WorkspaceCRMConnection)
            .join(
                WorkspaceCRMConnection,
                WorkspaceCRMConnection.connection_id == CRMConnection.id,
            )
            .where(
                CRMConnection.id == saved.connection_id,
                CRMConnection.tenant_id == saved.tenant_id,
                CRMConnection.provider == CRMProvider.ZOHO.value,
                WorkspaceCRMConnection.tenant_id == saved.tenant_id,
            )
        )
    ).first()
    if row is None:
        return RedirectResponse(
            redirect_target(
                frontend_url,
                crm="failed",
                provider="zoho",
                reason="connection_not_found",
            ),
            status_code=303,
        )
    connection, scope = row[0], row[1]
    workspace_id = scope.workspace_id
    connection_id = connection.id
    configured_frontend = str(
        (connection.configuration_json or {}).get("oneClickFrontendReturnUrl") or ""
    ).strip()
    if configured_frontend:
        frontend_url = configured_frontend

    if error or not code:
        connection.status = CRMConnectionStatus.AUTH_REQUIRED.value
        connection.last_failure_at = datetime.now(UTC)
        connection.last_error = f"Zoho authorization was not completed: {error or 'missing_code'}"[:1000]
        record_integration_audit(
            session,
            tenant_id=saved.tenant_id,
            workspace_id=workspace_id,
            actor_user_id=saved.user_id,
            action="crm.zoho.one_click.authorization.denied",
            entity_type="crm_connection",
            entity_id=str(connection.id),
            severity="warning",
            outcome="failure",
            metadata={"reason": error or "missing_code"},
        )
        await session.commit()
        return RedirectResponse(
            redirect_target(
                frontend_url,
                crm="failed",
                provider="zoho",
                connectionId=str(connection_id),
                reason="authorization_not_completed",
            ),
            status_code=303,
        )

    if platform is None:
        connection.status = CRMConnectionStatus.CONFIGURATION_ERROR.value
        connection.last_error = "The platform-managed Zoho OAuth application is not configured"
        connection.last_failure_at = datetime.now(UTC)
        await session.commit()
        return RedirectResponse(
            redirect_target(
                frontend_url,
                crm="failed",
                provider="zoho",
                connectionId=str(connection_id),
                reason="platform_oauth_not_configured",
            ),
            status_code=303,
        )

    try:
        accounts_url, api_domain, resolved_location = resolve_zoho_data_center(
            location=location,
            accounts_server=accounts_server,
            default_accounts_url=platform.accounts_url,
            default_api_domain=platform.api_domain,
        )
        connector = crm_registry.get(CRMProvider.ZOHO)
        existing = decrypt_zoho_credentials(connection)
        existing.update(
            {
                "client_id": platform.client_id,
                "client_secret": platform.client_secret_for(resolved_location),
                "accounts_url": accounts_url,
            }
        )
        regional_configuration = {
            **dict(connection.configuration_json or {}),
            "accountsUrl": accounts_url,
            "apiDomain": api_domain,
            "dataCenter": resolved_location,
        }
        connection.configuration_json = regional_configuration
        context = CRMConnectionContext(
            tenant_id=saved.tenant_id,
            connection_id=connection.id,
            provider=CRMProvider.ZOHO,
            configuration=regional_configuration,
            credentials=existing,
        )
        updated = await connector.exchange_authorization_code(
            context,
            code=code,
            redirect_uri=saved.redirect_uri,
            code_verifier=None,
        )
        updated["accounts_url"] = accounts_url
        resolved_api_domain = str(updated.get("api_domain") or api_domain).rstrip("/")
        connection.configuration_json = {
            **regional_configuration,
            "apiDomain": resolved_api_domain,
        }
        connection.credentials_encrypted = credential_store.encrypt(updated)
        connection.last_authenticated_at = datetime.now(UTC)
        connection.status = CRMConnectionStatus.CONNECTING.value
        connection.last_error = None
        # Preserve a successful grant even if schema discovery or certification
        # fails later. The route remains disabled until the full proof succeeds.
        await session.commit()
        await set_tenant_context(session, saved.tenant_id)
        authorized = await session.scalar(
            select(CRMConnection).where(
                CRMConnection.id == connection_id,
                CRMConnection.tenant_id == saved.tenant_id,
            )
        )
        if authorized is None:
            raise ZohoOneClickError("Zoho connection disappeared after authorization")
        result = await bootstrap_zoho_connection(
            session,
            connection=authorized,
            workspace_id=workspace_id,
            actor_user_id=saved.user_id,
            platform=platform,
        )
        await session.commit()
        return RedirectResponse(
            redirect_target(
                frontend_url,
                crm="connected",
                provider="zoho",
                connectionId=str(connection_id),
                liveTest=result.certification_status,
                externalRecordId=result.external_record_id,
            ),
            status_code=303,
        )
    except (
        CRMError,
        CredentialStoreError,
        ZohoOneClickError,
        ZohoPlatformConfigurationError,
        ValueError,
    ) as exc:
        await session.rollback()
        await set_tenant_context(session, saved.tenant_id)
        failed = await session.scalar(
            select(CRMConnection).where(
                CRMConnection.id == saved.connection_id,
                CRMConnection.tenant_id == saved.tenant_id,
            )
        )
        if failed is not None:
            failed.status = normalized_failure_status(exc)
            failed.last_failure_at = datetime.now(UTC)
            failed.last_error = str(exc)[:1000] or "Zoho bootstrap failed"
            configuration = dict(failed.configuration_json or {})
            configuration["liveCertification"] = {
                "status": "failed",
                "failedAt": datetime.now(UTC).isoformat(),
                "reason": "zoho_bootstrap_failed",
            }
            failed.configuration_json = configuration
            record_integration_audit(
                session,
                tenant_id=saved.tenant_id,
                workspace_id=workspace_id,
                actor_user_id=saved.user_id,
                action="crm.zoho.one_click.certification.failed",
                entity_type="crm_connection",
                entity_id=str(failed.id),
                severity="warning",
                outcome="failure",
                metadata={"reason": "zoho_bootstrap_failed"},
            )
            await session.commit()
        return RedirectResponse(
            redirect_target(
                frontend_url,
                crm="failed",
                provider="zoho",
                connectionId=str(connection_id),
                reason="zoho_bootstrap_failed",
            ),
            status_code=303,
        )
