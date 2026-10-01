from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response

from northstar_api.dependencies import DBSession
from northstar_api.modules.branding.services import resolve_published_workspace_brand
from northstar_api.modules.workspace.brand_cache import cache_domain_brand, cached_domain_brand
from northstar_api.modules.workspace.domain_resolution import normalize_hostname, resolve_workspace_domain
from northstar_api.onboarding_contract import SetupContract

router = APIRouter(prefix="/branding", tags=["public-branding"])


class PublicBrandingResponse(SetupContract):
    workspace_id: UUID
    company_name: str
    browser_title: str
    logo_data_url: str
    favicon_data_url: str
    primary_color: str
    secondary_color: str
    colors: dict[str, str]
    typography: dict[str, str | int | float]
    authentication: dict[str, Any]
    support_url: str


def _hostname(value: str) -> str:
    try:
        return normalize_hostname(value)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid hostname") from None


@router.get("/health", status_code=204)
async def branding_health() -> Response:
    return Response(status_code=204)


@router.get("/public", response_model=PublicBrandingResponse)
async def public_branding(
    session: DBSession,
    hostname: str = Query(min_length=4, max_length=253),
) -> PublicBrandingResponse:
    normalized = _hostname(hostname)
    cached = await cached_domain_brand(normalized)
    if cached is not None:
        try:
            return PublicBrandingResponse.model_validate(cached)
        except (TypeError, ValueError):
            pass

    workspace = await resolve_workspace_domain(session, normalized)
    if workspace is None:
        raise HTTPException(status_code=404, detail="No active brand is configured for this domain")
    published, _ = await resolve_published_workspace_brand(session, workspace)
    if published is None or not published.identity.branded_login:
        raise HTTPException(status_code=404, detail="No active login brand is configured for this domain")
    identity = published.identity
    response = PublicBrandingResponse(
        workspace_id=workspace.id,
        company_name=identity.company_name,
        browser_title=identity.browser_title,
        logo_data_url=identity.logo_data_url,
        favicon_data_url=identity.favicon_data_url,
        primary_color=identity.primary_color,
        secondary_color=identity.secondary_color,
        colors=published.colors.model_dump(mode="json"),
        typography=published.typography.model_dump(mode="json"),
        authentication=published.authentication.model_dump(by_alias=True, mode="json"),
        support_url=identity.support_url,
    )
    await cache_domain_brand(normalized, response.model_dump(mode="json"))
    return response
