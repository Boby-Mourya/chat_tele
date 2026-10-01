from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlencode

import httpx

from northstar_api.lead_crm.connectors import (
    CRMCapabilities,
    CRMConnectionContext,
    CRMConnector,
    CRMDeliveryResult,
    CRMError,
    CRMFieldDefinition,
    CRMHealthResult,
)
from northstar_api.lead_crm.domain import (
    CRMOperation,
    CRMProvider,
    IntegrationHealthStatus,
    NormalizedCRMErrorCode,
)


class ZohoCRMConnector(CRMConnector):
    provider = CRMProvider.ZOHO
    capabilities = CRMCapabilities(
        oauth=True,
        schema_discovery=True,
        create=True,
        update=True,
        upsert=True,
        read_back=True,
        inbound_webhooks=True,
        webhook_management=True,
    )

    @staticmethod
    def _accounts_url(context: CRMConnectionContext) -> str:
        return str(
            context.configuration.get("accountsUrl")
            or context.credentials.get("accounts_url")
            or "https://accounts.zoho.com"
        ).rstrip("/")

    @staticmethod
    def _api_domain(context: CRMConnectionContext) -> str:
        return str(
            context.configuration.get("apiDomain")
            or context.credentials.get("api_domain")
            or "https://www.zohoapis.com"
        ).rstrip("/")

    @staticmethod
    def _version(context: CRMConnectionContext) -> str:
        return str(context.configuration.get("apiVersion") or "v8")

    def build_authorization_url(
        self,
        context: CRMConnectionContext,
        *,
        redirect_uri: str,
        state: str,
        code_challenge: str | None = None,
    ) -> str:
        client_id = context.credentials.get("client_id")
        if not client_id:
            raise CRMError(
                NormalizedCRMErrorCode.CONFIGURATION_ERROR,
                "Zoho OAuth client_id is not configured",
            )
        scopes = context.configuration.get("oauthScopes") or [
            "ZohoCRM.modules.ALL",
            "ZohoCRM.settings.ALL",
            "ZohoCRM.org.READ",
        ]
        params = {
            "scope": ",".join(str(item) for item in scopes),
            "client_id": str(client_id),
            "response_type": "code",
            "access_type": "offline",
            "prompt": "consent",
            "redirect_uri": redirect_uri,
            "state": state,
        }
        return f"{self._accounts_url(context)}/oauth/v2/auth?{urlencode(params)}"

    async def exchange_authorization_code(
        self,
        context: CRMConnectionContext,
        *,
        code: str,
        redirect_uri: str,
        code_verifier: str | None = None,
    ) -> dict[str, Any]:
        credentials = dict(context.credentials)
        client_id = credentials.get("client_id")
        client_secret = credentials.get("client_secret")
        if not client_id or not client_secret:
            raise CRMError(
                NormalizedCRMErrorCode.CONFIGURATION_ERROR,
                "Zoho OAuth client credentials are incomplete",
            )
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
                response = await client.post(
                    f"{self._accounts_url(context)}/oauth/v2/token",
                    data={
                        "grant_type": "authorization_code",
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "redirect_uri": redirect_uri,
                        "code": code,
                    },
                    headers={"Accept": "application/json"},
                )
        except httpx.TimeoutException as exc:
            raise CRMError(
                NormalizedCRMErrorCode.TIMEOUT, "Zoho OAuth exchange timed out", retryable=True
            ) from exc
        except httpx.HTTPError as exc:
            raise CRMError(
                NormalizedCRMErrorCode.NETWORK_ERROR, "Zoho OAuth exchange failed", retryable=True
            ) from exc
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
        url = f"{self._accounts_url(context)}/oauth/v2/token"
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
                response = await client.post(
                    url,
                    data={
                        "refresh_token": refresh_token,
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "grant_type": "refresh_token",
                    },
                    headers={"Accept": "application/json"},
                )
        except httpx.TimeoutException as exc:
            raise CRMError(
                NormalizedCRMErrorCode.TIMEOUT, "Zoho OAuth refresh timed out", retryable=True
            ) from exc
        except httpx.HTTPError as exc:
            raise CRMError(
                NormalizedCRMErrorCode.NETWORK_ERROR, "Zoho OAuth refresh failed", retryable=True
            ) from exc
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

    async def _credentials_with_access(self, context: CRMConnectionContext) -> dict[str, Any]:
        credentials = dict(context.credentials)
        access_token = credentials.get("access_token")
        expires_at = int(credentials.get("access_token_expires_at") or 0)
        if access_token and (expires_at == 0 or expires_at > int(time.time()) + 120):
            return credentials
        return await self.refresh_credentials(context)

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
            async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
                response = await client.request(method, url, params=params, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise CRMError(
                NormalizedCRMErrorCode.TIMEOUT, "Zoho CRM request timed out", retryable=True
            ) from exc
        except httpx.HTTPError as exc:
            raise CRMError(
                NormalizedCRMErrorCode.NETWORK_ERROR, "Zoho CRM network request failed", retryable=True
            ) from exc
        if response.status_code < 400:
            return response
        code = None
        try:
            body = response.json()
            if isinstance(body, dict):
                code = body.get("code")
                if code is None and isinstance(body.get("data"), list) and body["data"]:
                    code = body["data"][0].get("code")
        except ValueError:
            pass
        code_text = str(code or f"http_{response.status_code}")
        if response.status_code == 429:
            retry_after = (
                int(response.headers["Retry-After"])
                if response.headers.get("Retry-After", "").isdigit()
                else None
            )
            raise CRMError(
                NormalizedCRMErrorCode.RATE_LIMIT_ERROR,
                "Zoho CRM rate limit reached",
                retryable=True,
                http_status=429,
                provider_code=code_text,
                retry_after_seconds=retry_after,
            )
        if response.status_code in {401, 403} or code_text in {"OAUTH_SCOPE_MISMATCH", "INVALID_TOKEN"}:
            raise CRMError(
                NormalizedCRMErrorCode.AUTHORIZATION_ERROR
                if response.status_code == 403
                else NormalizedCRMErrorCode.AUTHENTICATION_ERROR,
                "Zoho CRM authorization failed",
                requires_reconnect=code_text == "INVALID_TOKEN",
                http_status=response.status_code,
                provider_code=code_text,
            )
        if response.status_code >= 500:
            raise CRMError(
                NormalizedCRMErrorCode.PROVIDER_UNAVAILABLE,
                "Zoho CRM is temporarily unavailable",
                retryable=True,
                http_status=response.status_code,
                provider_code=code_text,
            )
        normalized = (
            NormalizedCRMErrorCode.DUPLICATE_ERROR
            if code_text == "DUPLICATE_DATA"
            else NormalizedCRMErrorCode.VALIDATION_ERROR
        )
        raise CRMError(
            normalized,
            "Zoho CRM rejected the request",
            http_status=response.status_code,
            provider_code=code_text,
        )

    @staticmethod
    def _parse_record_result(response: httpx.Response, operation: CRMOperation) -> CRMDeliveryResult:
        try:
            body = response.json()
        except ValueError as exc:
            raise CRMError(NormalizedCRMErrorCode.VALIDATION_ERROR, "Zoho CRM returned invalid JSON") from exc
        records = body.get("data") if isinstance(body, dict) else None
        if not isinstance(records, list) or not records or not isinstance(records[0], dict):
            raise CRMError(
                NormalizedCRMErrorCode.VALIDATION_ERROR, "Zoho CRM returned no record acknowledgement"
            )
        result = records[0]
        if result.get("status") != "success":
            code = str(result.get("code") or "unknown")
            retryable = code in {"INTERNAL_ERROR", "LOCKED", "RECORD_LOCKED"}
            raise CRMError(
                NormalizedCRMErrorCode.PROVIDER_UNAVAILABLE
                if retryable
                else NormalizedCRMErrorCode.VALIDATION_ERROR,
                "Zoho CRM did not acknowledge the record",
                retryable=retryable,
                http_status=response.status_code,
                provider_code=code,
            )
        details_value = result.get("details")
        details: dict[str, Any] = dict(details_value) if isinstance(details_value, dict) else {}
        record_id = details.get("id")
        return CRMDeliveryResult(
            accepted=True,
            operation=operation,
            external_record_id=str(record_id) if record_id is not None else None,
            http_status=response.status_code,
            provider_code=str(result.get("code") or "SUCCESS"),
            provider_request_id=response.headers.get("X-Request-ID")
            or response.headers.get("X-ZOHO-REQUEST-ID"),
            metadata={"action": result.get("action"), "message": result.get("message")},
        )

    async def health_check(self, context: CRMConnectionContext) -> CRMHealthResult:
        started = time.monotonic()
        try:
            response = await self._request(context, method="GET", path="settings/modules")
            healthy = response.status_code < 400
            return CRMHealthResult(
                status=IntegrationHealthStatus.HEALTHY if healthy else IntegrationHealthStatus.UNHEALTHY,
                checks={"credentials": "up", "oauth": "up", "api": "up" if healthy else "down"},
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        except CRMError as exc:
            status = (
                IntegrationHealthStatus.AUTH_REQUIRED
                if exc.requires_reconnect
                else IntegrationHealthStatus.UNHEALTHY
            )
            return CRMHealthResult(
                status=status,
                checks={
                    "credentials": "down" if exc.requires_reconnect else "unknown",
                    "oauth": "down" if exc.requires_reconnect else "unknown",
                    "api": "down",
                },
                latency_ms=int((time.monotonic() - started) * 1000),
                details={"error": exc.code.value, "providerCode": exc.provider_code},
            )

    async def discover_schema(
        self, context: CRMConnectionContext, object_name: str = "Leads"
    ) -> list[CRMFieldDefinition]:
        response = await self._request(
            context,
            method="GET",
            path="settings/fields",
            params={"module": object_name, "include": "allowed_permissions_to_update"},
        )
        body = response.json()
        fields = body.get("fields") if isinstance(body, dict) else None
        if not isinstance(fields, list):
            raise CRMError(NormalizedCRMErrorCode.VALIDATION_ERROR, "Zoho field metadata response is invalid")
        definitions: list[CRMFieldDefinition] = []
        for raw in fields:
            if not isinstance(raw, dict) or not raw.get("api_name"):
                continue
            pick_values = raw.get("pick_list_values") or []
            definitions.append(
                CRMFieldDefinition(
                    api_name=str(raw["api_name"]),
                    label=str(raw.get("field_label") or raw["api_name"]),
                    data_type=str(raw.get("data_type") or "unknown"),
                    required=bool(raw.get("system_mandatory")),
                    nullable=not bool(raw.get("system_mandatory")),
                    read_only=bool(raw.get("read_only")),
                    unique=bool(raw.get("unique") or raw.get("external")),
                    custom=bool(raw.get("custom_field")),
                    max_length=int(raw["length"]) if isinstance(raw.get("length"), int) else None,
                    picklist_values=tuple(
                        str(item.get("display_value") or item.get("actual_value"))
                        for item in pick_values
                        if isinstance(item, dict)
                    ),
                    metadata={"id": raw.get("id")},
                )
            )
        return definitions

    async def create_lead(
        self, context: CRMConnectionContext, payload: dict[str, Any], *, idempotency_key: str
    ) -> CRMDeliveryResult:
        trigger = context.configuration.get("trigger", ["workflow"])
        response = await self._request(
            context, method="POST", path="Leads", payload={"data": [payload], "trigger": trigger}
        )
        return self._parse_record_result(response, CRMOperation.CREATE)

    async def update_lead(
        self,
        context: CRMConnectionContext,
        external_id: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> CRMDeliveryResult:
        trigger = context.configuration.get("trigger", ["workflow"])
        response = await self._request(
            context,
            method="PUT",
            path="Leads",
            payload={"data": [{"id": external_id, **payload}], "trigger": trigger},
        )
        result = self._parse_record_result(response, CRMOperation.UPDATE)
        return CRMDeliveryResult(
            result.accepted,
            CRMOperation.UPDATE,
            result.external_record_id or external_id,
            result.http_status,
            result.provider_code,
            result.provider_request_id,
            metadata=result.metadata,
        )

    async def upsert_lead(
        self, context: CRMConnectionContext, payload: dict[str, Any], *, idempotency_key: str
    ) -> CRMDeliveryResult:
        duplicate_fields = context.configuration.get("duplicateCheckFields") or ["Email"]
        trigger = context.configuration.get("trigger", ["workflow"])
        response = await self._request(
            context,
            method="POST",
            path="Leads/upsert",
            payload={
                "data": [payload],
                "duplicate_check_fields": duplicate_fields,
                "trigger": trigger,
            },
        )
        return self._parse_record_result(response, CRMOperation.UPSERT)

    async def get_lead(self, context: CRMConnectionContext, external_id: str) -> dict[str, Any]:
        response = await self._request(context, method="GET", path=f"Leads/{external_id}")
        body = response.json()
        values = body.get("data") if isinstance(body, dict) else None
        if not isinstance(values, list) or not values or not isinstance(values[0], dict):
            raise CRMError(NormalizedCRMErrorCode.VALIDATION_ERROR, "Zoho lead read-back returned no record")
        return values[0]
