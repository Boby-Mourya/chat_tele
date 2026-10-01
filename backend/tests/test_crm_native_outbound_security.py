from __future__ import annotations

import ipaddress
import time
from typing import Any
from uuid import uuid4

import httpx
import pytest

from northstar_api.lead_crm import providers as provider_registry
from northstar_api.lead_crm import safe_http
from northstar_api.lead_crm.connectors import CRMConnectionContext, CRMConnector, CRMError, crm_registry
from northstar_api.lead_crm.domain import CRMProvider, NormalizedCRMErrorCode
from northstar_api.lead_crm.providers import secure_native
from northstar_api.lead_crm.providers.secure_native import (
    SecureDynamics365Connector,
    SecureFreshsalesConnector,
    SecureHubSpotConnector,
    SecurePipedriveConnector,
    SecureSalesforceConnector,
    SecureZohoCRMConnector,
)
from northstar_api.services import safe_fetch


def _context(
    provider: CRMProvider,
    *,
    configuration: dict[str, Any] | None = None,
    credentials: dict[str, Any] | None = None,
) -> CRMConnectionContext:
    return CRMConnectionContext(
        tenant_id=uuid4(),
        connection_id=uuid4(),
        provider=provider,
        configuration=configuration or {},
        credentials=credentials or {},
    )


@pytest.mark.parametrize(
    ("connector_type", "provider"),
    [
        (SecureSalesforceConnector, CRMProvider.SALESFORCE),
        (SecureHubSpotConnector, CRMProvider.HUBSPOT),
        (SecureDynamics365Connector, CRMProvider.DYNAMICS365),
        (SecurePipedriveConnector, CRMProvider.PIPEDRIVE),
        (SecureFreshsalesConnector, CRMProvider.FRESHSALES),
        (SecureZohoCRMConnector, CRMProvider.ZOHO),
    ],
)
def test_hardened_native_connectors_remain_concrete_and_provider_compatible(
    connector_type: type[CRMConnector],
    provider: CRMProvider,
) -> None:
    assert connector_type().provider is provider


def test_default_registry_selects_hardened_native_connectors() -> None:
    previous = dict(crm_registry._connectors)
    try:
        crm_registry._connectors.clear()
        provider_registry.register_default_connectors()
        assert isinstance(crm_registry._connectors[CRMProvider.SALESFORCE], SecureSalesforceConnector)
        assert isinstance(crm_registry._connectors[CRMProvider.HUBSPOT], SecureHubSpotConnector)
        assert isinstance(crm_registry._connectors[CRMProvider.DYNAMICS365], SecureDynamics365Connector)
        assert isinstance(crm_registry._connectors[CRMProvider.PIPEDRIVE], SecurePipedriveConnector)
        assert isinstance(crm_registry._connectors[CRMProvider.FRESHSALES], SecureFreshsalesConnector)
        assert isinstance(crm_registry._connectors[CRMProvider.ZOHO], SecureZohoCRMConnector)
    finally:
        crm_registry._connectors.clear()
        crm_registry._connectors.update(previous)


@pytest.mark.asyncio
async def test_safe_public_transport_rejects_private_resolution_before_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def private_lookup(_: str, __: int) -> tuple[str, ...]:
        return ("127.0.0.1",)

    monkeypatch.setattr(safe_fetch, "_lookup_addresses", private_lookup)

    with pytest.raises(safe_http.UnsafeOutboundCRMURL, match="non-public network"):
        await safe_http.request_public("GET", "https://private.example/api")


@pytest.mark.asyncio
async def test_safe_public_transport_pins_dns_and_forwards_form_and_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = safe_fetch._ResolvedTarget(
        url=httpx.URL("https://crm.example/oauth/token"),
        hostname="crm.example",
        port=443,
        addresses=(ipaddress.ip_address("93.184.216.34"),),
    )
    seen: dict[str, Any] = {}

    async def resolve(url: str) -> safe_fetch._ResolvedTarget:
        assert url == "https://crm.example/oauth/token"
        return target

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["host"] = request.headers.get("Host")
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"access_token": "ok"}, request=request)

    monkeypatch.setattr(safe_fetch, "_resolve_public_target", resolve)
    monkeypatch.setattr(safe_fetch, "_new_transport", lambda: httpx.MockTransport(handler))

    response = await safe_http.request_public(
        "POST",
        "https://crm.example/oauth/token",
        params={"region": "us"},
        form_data={"grant_type": "refresh_token", "refresh_token": "secret"},
        headers={"Accept": "application/json"},
    )

    assert response.status_code == 200
    assert seen["url"] == "https://93.184.216.34/oauth/token?region=us"
    assert seen["host"] == "crm.example"
    assert "grant_type=refresh_token" in seen["body"]
    assert "refresh_token=secret" in seen["body"]


@pytest.mark.asyncio
async def test_salesforce_api_requests_use_safe_public_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    async def fake_request_public(method: str, url: str, **_: Any) -> httpx.Response:
        calls.append((method, url))
        request = httpx.Request(method, url)
        return httpx.Response(200, json={"ok": True}, request=request)

    monkeypatch.setattr(secure_native, "request_public", fake_request_public)
    connector = SecureSalesforceConnector()
    context = _context(
        CRMProvider.SALESFORCE,
        configuration={"instanceUrl": "https://tenant.my.salesforce.com", "apiVersion": "v61.0"},
        credentials={
            "access_token": "token",
            "access_token_expires_at": int(time.time()) + 3600,
        },
    )

    response = await connector._request(context, "GET", "limits")

    assert response.status_code == 200
    assert calls == [("GET", "https://tenant.my.salesforce.com/services/data/v61.0/limits")]


@pytest.mark.asyncio
async def test_native_oauth_rejects_unsafe_token_destination(monkeypatch: pytest.MonkeyPatch) -> None:
    async def blocked(*_: Any, **__: Any) -> httpx.Response:
        raise safe_http.UnsafeOutboundCRMURL("private destination")

    monkeypatch.setattr(secure_native, "request_public", blocked)
    connector = SecureHubSpotConnector()
    context = _context(
        CRMProvider.HUBSPOT,
        configuration={"tokenUrl": "https://127.0.0.1/oauth/token"},
        credentials={"client_id": "client", "client_secret": "secret"},
    )

    with pytest.raises(CRMError) as captured:
        await connector.exchange_authorization_code(
            context,
            code="code",
            redirect_uri="https://app.example/callback",
        )

    assert captured.value.code is NormalizedCRMErrorCode.CONFIGURATION_ERROR
    assert "public HTTPS" in str(captured.value)


@pytest.mark.asyncio
async def test_zoho_api_rejects_unsafe_credential_domain(monkeypatch: pytest.MonkeyPatch) -> None:
    async def blocked(*_: Any, **__: Any) -> httpx.Response:
        raise safe_http.UnsafeOutboundCRMURL("private destination")

    monkeypatch.setattr(secure_native, "request_public", blocked)
    connector = SecureZohoCRMConnector()
    context = _context(
        CRMProvider.ZOHO,
        credentials={
            "access_token": "token",
            "access_token_expires_at": int(time.time()) + 3600,
            "api_domain": "https://127.0.0.1",
        },
    )

    with pytest.raises(CRMError) as captured:
        await connector._request(context, method="GET", path="Leads")

    assert captured.value.code is NormalizedCRMErrorCode.CONFIGURATION_ERROR
    assert "public HTTPS" in str(captured.value)
