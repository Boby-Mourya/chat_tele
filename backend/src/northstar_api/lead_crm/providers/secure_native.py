from __future__ import annotations

import base64
import time
from typing import Any

import httpx

from northstar_api.lead_crm.connectors import CRMConnectionContext, CRMError
from northstar_api.lead_crm.domain import NormalizedCRMErrorCode
from northstar_api.lead_crm.providers.native_v2 import (
    Dynamics365Connector,
    FreshsalesConnector,
    HubSpotConnector,
    OAuthJSONConnector,
    PipedriveConnector,
    SalesforceConnector,
)
from northstar_api.lead_crm.providers.zoho import ZohoCRMConnector
from northstar_api.lead_crm.safe_http import UnsafeOutboundCRMURL, request_public


def _retry_after(response: httpx.Response) -> int | None:
    value = response.headers.get("Retry-After", "")
    return int(value) if value.isdigit() else None


def _raise_native_http_error(response: httpx.Response) -> None:
    if response.status_code == 429:
        raise CRMError(
            NormalizedCRMErrorCode.RATE_LIMIT_ERROR,
            "CRM rate limit reached",
            retryable=True,
            http_status=429,
            retry_after_seconds=_retry_after(response),
        )
    if response.status_code in {401, 403}:
        raise CRMError(
            NormalizedCRMErrorCode.AUTHENTICATION_ERROR
            if response.status_code == 401
            else NormalizedCRMErrorCode.AUTHORIZATION_ERROR,
            "CRM authorization failed",
            requires_reconnect=response.status_code == 401,
            http_status=response.status_code,
        )
    if response.status_code >= 500:
        raise CRMError(
            NormalizedCRMErrorCode.PROVIDER_UNAVAILABLE,
            "CRM provider is temporarily unavailable",
            retryable=True,
            http_status=response.status_code,
        )
    raise CRMError(
        NormalizedCRMErrorCode.VALIDATION_ERROR,
        "CRM rejected the request",
        http_status=response.status_code,
    )


class HardenedOAuthJSONConnector(OAuthJSONConnector):
    """Preserve native provider behavior while pinning every server-side destination."""

    async def _post_token(
        self,
        context: CRMConnectionContext,
        data: dict[str, str],
        *,
        use_basic_auth: bool = False,
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        if use_basic_auth:
            client_id, client_secret = self._client_credentials(context)
            encoded = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"
            data = {key: value for key, value in data.items() if key not in {"client_id", "client_secret"}}
        try:
            response = await request_public(
                "POST",
                self._token_endpoint(context),
                form_data=data,
                headers=headers,
                timeout_seconds=20,
            )
        except UnsafeOutboundCRMURL as exc:
            raise CRMError(
                NormalizedCRMErrorCode.CONFIGURATION_ERROR,
                "CRM OAuth token destination is not a permitted public HTTPS URL",
            ) from exc
        except httpx.TimeoutException as exc:
            raise CRMError(
                NormalizedCRMErrorCode.TIMEOUT,
                "OAuth token request timed out",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise CRMError(
                NormalizedCRMErrorCode.NETWORK_ERROR,
                "OAuth token request failed",
                retryable=True,
            ) from exc

        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code >= 400 or not isinstance(body, dict) or not body.get("access_token"):
            code = (
                str(body.get("error") or body.get("errorCode") or "oauth_failed")
                if isinstance(body, dict)
                else "oauth_failed"
            )
            raise CRMError(
                NormalizedCRMErrorCode.AUTHENTICATION_ERROR,
                "OAuth token request was rejected",
                retryable=response.status_code >= 500,
                requires_reconnect=response.status_code in {400, 401},
                http_status=response.status_code,
                provider_code=code,
            )
        return body

    async def _request(
        self,
        context: CRMConnectionContext,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> httpx.Response:
        credentials = await self._access_credentials(context)
        token = str(credentials.get("access_token") or "")
        if not token:
            raise CRMError(
                NormalizedCRMErrorCode.AUTHENTICATION_ERROR,
                "Access token is missing",
                requires_reconnect=True,
            )
        url = f"{self._base_url(context, credentials).rstrip('/')}/{path.lstrip('/')}"
        try:
            response = await request_public(
                method,
                url,
                params=params,
                json_body=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                timeout_seconds=20,
            )
        except UnsafeOutboundCRMURL as exc:
            raise CRMError(
                NormalizedCRMErrorCode.CONFIGURATION_ERROR,
                "CRM API destination is not a permitted public HTTPS URL",
            ) from exc
        except httpx.TimeoutException as exc:
            raise CRMError(
                NormalizedCRMErrorCode.TIMEOUT,
                "CRM request timed out",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise CRMError(
                NormalizedCRMErrorCode.NETWORK_ERROR,
                "CRM request failed",
                retryable=True,
            ) from exc
        if response.status_code < 400:
            return response
        _raise_native_http_error(response)
        raise AssertionError("unreachable")


class SecureSalesforceConnector(HardenedOAuthJSONConnector, SalesforceConnector):
    pass


class SecureHubSpotConnector(HardenedOAuthJSONConnector, HubSpotConnector):
    pass


class SecureDynamics365Connector(HardenedOAuthJSONConnector, Dynamics365Connector):
    pass


class SecurePipedriveConnector(HardenedOAuthJSONConnector, PipedriveConnector):
    pass


class SecureFreshsalesConnector(FreshsalesConnector):
    async def _request(
        self,
        context: CRMConnectionContext,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> httpx.Response:
        api_key = str(context.credentials.get("api_key") or "")
        if not api_key:
            raise CRMError(
                NormalizedCRMErrorCode.AUTHENTICATION_ERROR,
                "Freshsales API key is missing",
                requires_reconnect=True,
            )
        try:
            response = await request_public(
                method,
                f"{self._base_url(context)}/{path.lstrip('/')}",
                params=params,
                json_body=payload,
                headers={
                    "Authorization": f"Token token={api_key}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                timeout_seconds=20,
            )
        except UnsafeOutboundCRMURL as exc:
            raise CRMError(
                NormalizedCRMErrorCode.CONFIGURATION_ERROR,
                "Freshsales API destination is not a permitted public HTTPS URL",
            ) from exc
        except httpx.TimeoutException as exc:
            raise CRMError(
                NormalizedCRMErrorCode.TIMEOUT, "Freshsales request timed out", retryable=True
            ) from exc
        except httpx.HTTPError as exc:
            raise CRMError(
                NormalizedCRMErrorCode.NETWORK_ERROR, "Freshsales request failed", retryable=True
            ) from exc
        if response.status_code < 400:
            return response
        _raise_native_http_error(response)
        raise AssertionError("unreachable")


class SecureZohoCRMConnector(ZohoCRMConnector):
    async def _post_zoho_token(
        self,
        context: CRMConnectionContext,
        data: dict[str, str],
        *,
        timeout_seconds: float,
    ) -> httpx.Response:
        try:
            return await request_public(
                "POST",
                f"{self._accounts_url(context)}/oauth/v2/token",
                form_data=data,
                headers={"Accept": "application/json"},
                timeout_seconds=timeout_seconds,
            )
        except UnsafeOutboundCRMURL as exc:
            raise CRMError(
                NormalizedCRMErrorCode.CONFIGURATION_ERROR,
                "Zoho OAuth destination is not a permitted public HTTPS URL",
            ) from exc
        except httpx.TimeoutException as exc:
            raise CRMError(
                NormalizedCRMErrorCode.TIMEOUT,
                "Zoho OAuth request timed out",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise CRMError(
                NormalizedCRMErrorCode.NETWORK_ERROR,
                "Zoho OAuth request failed",
                retryable=True,
            ) from exc

    async def exchange_authorization_code(
        self,
        context: CRMConnectionContext,
        *,
        code: str,
        redirect_uri: str,
        code_verifier: str | None = None,
    ) -> dict[str, Any]:
        del code_verifier
        credentials = dict(context.credentials)
        client_id = credentials.get("client_id")
        client_secret = credentials.get("client_secret")
        if not client_id or not client_secret:
            raise CRMError(
                NormalizedCRMErrorCode.CONFIGURATION_ERROR,
                "Zoho OAuth client credentials are incomplete",
            )
        response = await self._post_zoho_token(
            context,
            {
                "grant_type": "authorization_code",
                "client_id": str(client_id),
                "client_secret": str(client_secret),
                "redirect_uri": redirect_uri,
                "code": code,
            },
            timeout_seconds=20,
        )
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code >= 400 or not isinstance(body, dict) or not body.get("access_token"):
            code_text = (
                str(body.get("error") or "oauth_exchange_failed")
                if isinstance(body, dict)
                else "oauth_exchange_failed"
            )
            raise CRMError(
                NormalizedCRMErrorCode.AUTHENTICATION_ERROR,
                "Zoho OAuth authorization was rejected",
                requires_reconnect=True,
                http_status=response.status_code,
                provider_code=code_text,
            )
        credentials["access_token"] = str(body["access_token"])
        credentials["access_token_expires_at"] = int(time.time()) + int(body.get("expires_in") or 3600)
        if body.get("refresh_token"):
            credentials["refresh_token"] = str(body["refresh_token"])
        if body.get("api_domain"):
            credentials["api_domain"] = str(body["api_domain"])
        return credentials

    async def refresh_credentials(self, context: CRMConnectionContext) -> dict[str, Any]:
        credentials = dict(context.credentials)
        refresh_token = credentials.get("refresh_token")
        client_id = credentials.get("client_id")
        client_secret = credentials.get("client_secret")
        if not refresh_token or not client_id or not client_secret:
            raise CRMError(
                NormalizedCRMErrorCode.AUTHENTICATION_ERROR,
                "Zoho OAuth refresh credentials are incomplete",
                requires_reconnect=True,
            )
        response = await self._post_zoho_token(
            context,
            {
                "refresh_token": str(refresh_token),
                "client_id": str(client_id),
                "client_secret": str(client_secret),
                "grant_type": "refresh_token",
            },
            timeout_seconds=15,
        )
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code >= 400 or not isinstance(body, dict) or not body.get("access_token"):
            code = (
                str(body.get("error") or body.get("code") or "oauth_refresh_failed")
                if isinstance(body, dict)
                else "oauth_refresh_failed"
            )
            permanent = code in {"invalid_code", "invalid_client", "invalid_client_secret", "invalid_grant"}
            raise CRMError(
                NormalizedCRMErrorCode.AUTHENTICATION_ERROR,
                "Zoho OAuth refresh was rejected",
                retryable=not permanent and response.status_code >= 500,
                requires_reconnect=permanent or response.status_code in {400, 401},
                http_status=response.status_code,
                provider_code=code,
            )
        expires_in = int(body.get("expires_in") or body.get("expires_in_sec") or 3600)
        credentials["access_token"] = str(body["access_token"])
        credentials["access_token_expires_at"] = int(time.time()) + expires_in
        if body.get("api_domain"):
            credentials["api_domain"] = str(body["api_domain"])
        return credentials

    async def _request(
        self,
        context: CRMConnectionContext,
        *,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> httpx.Response:
        credentials = await self._credentials_with_access(context)
        api_domain = str(credentials.get("api_domain") or self._api_domain(context)).rstrip("/")
        url = f"{api_domain}/crm/{self._version(context)}/{path.lstrip('/')}"
        headers = {
            "Authorization": f"Zoho-oauthtoken {credentials['access_token']}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        try:
            response = await request_public(
                method,
                url,
                params=params,
                json_body=payload,
                headers=headers,
                timeout_seconds=20,
            )
        except UnsafeOutboundCRMURL as exc:
            raise CRMError(
                NormalizedCRMErrorCode.CONFIGURATION_ERROR,
                "Zoho CRM API destination is not a permitted public HTTPS URL",
            ) from exc
        except httpx.TimeoutException as exc:
            raise CRMError(
                NormalizedCRMErrorCode.TIMEOUT,
                "Zoho CRM request timed out",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise CRMError(
                NormalizedCRMErrorCode.NETWORK_ERROR,
                "Zoho CRM network request failed",
                retryable=True,
            ) from exc
        if response.status_code < 400:
            return response

        provider_code = None
        try:
            body = response.json()
            if isinstance(body, dict):
                provider_code = body.get("code")
                if provider_code is None and isinstance(body.get("data"), list) and body["data"]:
                    first = body["data"][0]
                    if isinstance(first, dict):
                        provider_code = first.get("code")
        except ValueError:
            pass
        code_text = str(provider_code or f"http_{response.status_code}")
        if response.status_code == 429:
            raise CRMError(
                NormalizedCRMErrorCode.RATE_LIMIT_ERROR,
                "Zoho CRM rate limit reached",
                retryable=True,
                http_status=response.status_code,
                provider_code=code_text,
                retry_after_seconds=_retry_after(response),
            )
        if response.status_code in {401, 403}:
            raise CRMError(
                NormalizedCRMErrorCode.AUTHENTICATION_ERROR
                if response.status_code == 401
                else NormalizedCRMErrorCode.AUTHORIZATION_ERROR,
                "Zoho CRM authorization failed",
                requires_reconnect=response.status_code == 401,
                http_status=response.status_code,
                provider_code=code_text,
            )
        if response.status_code >= 500:
            raise CRMError(
                NormalizedCRMErrorCode.PROVIDER_UNAVAILABLE,
                "Zoho CRM provider is temporarily unavailable",
                retryable=True,
                http_status=response.status_code,
                provider_code=code_text,
            )
        raise CRMError(
            NormalizedCRMErrorCode.VALIDATION_ERROR,
            "Zoho CRM rejected the request",
            http_status=response.status_code,
            provider_code=code_text,
        )


__all__ = [
    "SecureDynamics365Connector",
    "SecureFreshsalesConnector",
    "SecureHubSpotConnector",
    "SecurePipedriveConnector",
    "SecureSalesforceConnector",
    "SecureZohoCRMConnector",
]
