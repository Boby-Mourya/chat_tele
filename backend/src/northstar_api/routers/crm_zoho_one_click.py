from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import get_session
from northstar_api.dependencies import AdminPrincipal
from northstar_api.lead_crm.connectors import CRMError
from northstar_api.lead_crm.credentials import CredentialStoreError
from northstar_api.routers.crm_oauth import _start_oauth
from northstar_api.services.zoho_one_click import (
    ZohoOneClickError,
    bootstrap_zoho_connection,
    ensure_workspace_zoho_connection,
    workspace_zoho_connection,
)
from northstar_api.services.zoho_one_click_oauth import process_zoho_one_click_callback
from northstar_api.services.zoho_one_click_status import zoho_connection_status
from northstar_api.zoho_platform import (
    ZohoPlatformConfiguration,
    ZohoPlatformConfigurationError,
    load_zoho_platform_configuration,
)

router = APIRouter(prefix="/crm/zoho/one-click", tags=["crm-zoho-one-click"])
DB = Annotated[AsyncSession, Depends(get_session)]


def _platform(*, required: bool) -> ZohoPlatformConfiguration | None:
    try:
        return load_zoho_platform_configuration(required=required)
    except ZohoPlatformConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _active_workspace(principal: AdminPrincipal) -> UUID:
    if principal.workspace_id is None:
        raise HTTPException(status_code=403, detail="An active workspace is required")
    return principal.workspace_id


@router.get("/status")
async def zoho_one_click_status_endpoint(
    principal: AdminPrincipal,
    session: DB,
) -> dict[str, Any]:
    workspace_id = _active_workspace(principal)
    return await zoho_connection_status(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        platform=_platform(required=False),
    )


@router.post("/start")
async def start_zoho_one_click(
    request: Request,
    principal: AdminPrincipal,
    session: DB,
) -> dict[str, Any]:
    platform = _platform(required=True)
    assert platform is not None
    workspace_id = _active_workspace(principal)
    try:
        connection, _, _ = await ensure_workspace_zoho_connection(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=workspace_id,
            actor_user_id=principal.user_id,
            platform=platform,
        )
        callback_url = platform.callback_url or str(request.url_for("zoho_one_click_callback"))
        connection.configuration_json = {
            **dict(connection.configuration_json or {}),
            "oauthRedirectUri": callback_url,
            "oneClickFrontendReturnUrl": platform.frontend_return_url,
        }
        await session.commit()
        result = await _start_oauth(
            connection.id,
            request,
            principal,
            session,
        )
    except (CredentialStoreError, ZohoOneClickError, CRMError) as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        **result,
        "oneClick": True,
        "willConfigureMapping": True,
        "willConfigureRouting": True,
        "willRunLiveCertification": platform.live_certification_enabled,
    }


@router.get("/callback", name="zoho_one_click_callback")
async def zoho_one_click_callback(
    session: DB,
    state: str = Query(min_length=20, max_length=512),
    code: str | None = Query(default=None, min_length=1, max_length=4096),
    error: str | None = Query(default=None, max_length=512),
    location: str | None = Query(default=None, max_length=20),
    accounts_server: str | None = Query(
        default=None,
        alias="accounts-server",
        max_length=256,
    ),
) -> RedirectResponse:
    return await process_zoho_one_click_callback(
        session,
        state=state,
        code=code,
        error=error,
        location=location,
        accounts_server=accounts_server,
        platform=_platform(required=False),
    )


@router.post("/certify")
async def certify_zoho_one_click(
    principal: AdminPrincipal,
    session: DB,
) -> dict[str, Any]:
    platform = _platform(required=True)
    assert platform is not None
    workspace_id = _active_workspace(principal)
    current = await workspace_zoho_connection(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
    )
    if current is None:
        raise HTTPException(status_code=404, detail="Connect Zoho before running certification")
    connection, _ = current
    try:
        result = await bootstrap_zoho_connection(
            session,
            connection=connection,
            workspace_id=workspace_id,
            actor_user_id=principal.user_id,
            platform=platform,
        )
        await session.commit()
    except (CRMError, CredentialStoreError, ZohoOneClickError, ValueError) as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "connectionId": str(result.connection_id),
        "mappingId": str(result.mapping_id),
        "routeId": str(result.route_id),
        "liveTest": result.certification_status,
        "externalRecordId": result.external_record_id,
        "verifiedFields": list(result.verified_fields),
    }
