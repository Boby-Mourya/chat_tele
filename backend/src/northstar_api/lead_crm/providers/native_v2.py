from __future__ import annotations

import base64
import time
from abc import abstractmethod
from typing import Any
from urllib.parse import quote, urlencode

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


class OAuthJSONConnector(CRMConnector):
    authorize_url = ""
    oauth_endpoint = ""
    default_scopes: tuple[str, ...] = ()

    def _client_credentials(self, context: CRMConnectionContext) -> tuple[str, str]:
        client_id = str(context.credentials.get("client_id") or "")
        client_secret = str(context.credentials.get("client_secret") or "")
        if not client_id or not client_secret:
            raise CRMError(
                NormalizedCRMErrorCode.CONFIGURATION_ERROR,
                f"{self.provider.value} OAuth client credentials are incomplete",
            )
        return client_id, client_secret

    def _authorization_endpoint(self, context: CRMConnectionContext) -> str:
        return str(context.configuration.get("authorizationUrl") or self.authorize_url)

    def _token_endpoint(self, context: CRMConnectionContext) -> str:
        return str(context.configuration.get("tokenUrl") or self.oauth_endpoint)

    def _scopes(self, context: CRMConnectionContext) -> list[str]:
        configured = context.configuration.get("oauthScopes")
        if isinstance(configured, list) and configured:
            return [str(item) for item in configured]
        return list(self.default_scopes)

    def build_authorization_url(
        self,
        context: CRMConnectionContext,
        *,
        redirect_uri: str,
        state: str,
        code_challenge: str | None = None,
    ) -> str:
        client_id, _ = self._client_credentials(context)
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": state,
        }
        scopes = self._scopes(context)
        if scopes:
            params["scope"] = " ".join(scopes)
        if code_challenge:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"
        return f"{self._authorization_endpoint(context)}?{urlencode(params)}"

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
            async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
                response = await client.post(self._token_endpoint(context), data=data, headers=headers)
        except httpx.TimeoutException as exc:
            raise CRMError(
                NormalizedCRMErrorCode.TIMEOUT, "OAuth token request timed out", retryable=True
            ) from exc
        except httpx.HTTPError as exc:
            raise CRMError(
                NormalizedCRMErrorCode.NETWORK_ERROR, "OAuth token request failed", retryable=True
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

    def _normalize_token(self, body: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {
            "access_token": str(body["access_token"]),
            "access_token_expires_at": int(time.time()) + int(body.get("expires_in") or 3600),
        }
        for source, target in (
            ("refresh_token", "refresh_token"),
            ("instance_url", "instance_url"),
            ("api_domain", "api_domain"),
        ):
            if body.get(source):
                result[target] = str(body[source])
        return result

    async def exchange_authorization_code(
        self,
        context: CRMConnectionContext,
        *,
        code: str,
        redirect_uri: str,
        code_verifier: str | None = None,
    ) -> dict[str, Any]:
        credentials = dict(context.credentials)
        client_id, client_secret = self._client_credentials(context)
        data = {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "code": code,
        }
        if code_verifier:
            data["code_verifier"] = code_verifier
        body = await self._post_token(context, data, use_basic_auth=self.provider == CRMProvider.PIPEDRIVE)
        credentials.update(self._normalize_token(body))
        return credentials

    async def refresh_credentials(self, context: CRMConnectionContext) -> dict[str, Any]:
        credentials = dict(context.credentials)
        refresh_token = str(credentials.get("refresh_token") or "")
        if not refresh_token:
            raise CRMError(
                NormalizedCRMErrorCode.AUTHENTICATION_ERROR,
                "Refresh token is missing",
                requires_reconnect=True,
            )
        client_id, client_secret = self._client_credentials(context)
        body = await self._post_token(
            context,
            {
                "grant_type": "refresh_token",
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
            },
            use_basic_auth=self.provider == CRMProvider.PIPEDRIVE,
        )
        credentials.update(self._normalize_token(body))
        credentials.setdefault("refresh_token", refresh_token)
        return credentials

    async def _access_credentials(self, context: CRMConnectionContext) -> dict[str, Any]:
        credentials = dict(context.credentials)
        expires_at = int(credentials.get("access_token_expires_at") or 0)
        if credentials.get("access_token") and (expires_at == 0 or expires_at > int(time.time()) + 120):
            return credentials
        return await self.refresh_credentials(context)

    @abstractmethod
    def _base_url(self, context: CRMConnectionContext, credentials: dict[str, Any]) -> str:
        raise NotImplementedError

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
            async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
                response = await client.request(
                    method,
                    url,
                    params=params,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                )
        except httpx.TimeoutException as exc:
            raise CRMError(NormalizedCRMErrorCode.TIMEOUT, "CRM request timed out", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise CRMError(
                NormalizedCRMErrorCode.NETWORK_ERROR, "CRM request failed", retryable=True
            ) from exc
        if response.status_code < 400:
            return response
        retry_after = (
            int(response.headers["Retry-After"])
            if response.headers.get("Retry-After", "").isdigit()
            else None
        )
        if response.status_code == 429:
            raise CRMError(
                NormalizedCRMErrorCode.RATE_LIMIT_ERROR,
                "CRM rate limit reached",
                retryable=True,
                http_status=429,
                retry_after_seconds=retry_after,
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

    async def health_check(self, context: CRMConnectionContext) -> CRMHealthResult:
        started = time.monotonic()
        try:
            await self._health_request(context)
            return CRMHealthResult(
                status=IntegrationHealthStatus.HEALTHY,
                checks={"credentials": "up", "oauth": "up", "api": "up"},
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        except CRMError as exc:
            return CRMHealthResult(
                status=IntegrationHealthStatus.AUTH_REQUIRED
                if exc.requires_reconnect
                else IntegrationHealthStatus.UNHEALTHY,
                checks={
                    "credentials": "down" if exc.requires_reconnect else "unknown",
                    "oauth": "down" if exc.requires_reconnect else "unknown",
                    "api": "down",
                },
                latency_ms=int((time.monotonic() - started) * 1000),
                details={"error": exc.code.value},
            )

    @abstractmethod
    async def _health_request(self, context: CRMConnectionContext) -> None:
        raise NotImplementedError


class SalesforceConnector(OAuthJSONConnector):
    provider = CRMProvider.SALESFORCE
    capabilities = CRMCapabilities(
        oauth=True,
        schema_discovery=True,
        create=True,
        update=True,
        upsert=True,
        read_back=True,
        inbound_webhooks=True,
    )
    authorize_url = "https://login.salesforce.com/services/oauth2/authorize"
    oauth_endpoint = "https://login.salesforce.com/services/oauth2/token"
    default_scopes = ("api", "refresh_token")

    def _authorization_endpoint(self, context: CRMConnectionContext) -> str:
        if str(context.configuration.get("environment") or "production") == "sandbox":
            return "https://test.salesforce.com/services/oauth2/authorize"
        return super()._authorization_endpoint(context)

    def _token_endpoint(self, context: CRMConnectionContext) -> str:
        if str(context.configuration.get("environment") or "production") == "sandbox":
            return "https://test.salesforce.com/services/oauth2/token"
        return super()._token_endpoint(context)

    def _base_url(self, context: CRMConnectionContext, credentials: dict[str, Any]) -> str:
        instance = credentials.get("instance_url") or context.configuration.get("instanceUrl")
        if not instance:
            raise CRMError(NormalizedCRMErrorCode.CONFIGURATION_ERROR, "Salesforce instance_url is missing")
        version = str(context.configuration.get("apiVersion") or "v61.0")
        return f"{str(instance).rstrip('/')}/services/data/{version}"

    async def _health_request(self, context: CRMConnectionContext) -> None:
        await self._request(context, "GET", "limits")

    async def discover_schema(
        self, context: CRMConnectionContext, object_name: str = "Lead"
    ) -> list[CRMFieldDefinition]:
        object_name = "Lead" if object_name == "Leads" else object_name
        response = await self._request(context, "GET", f"sobjects/{quote(object_name, safe='')}/describe")
        body = response.json()
        fields = body.get("fields") if isinstance(body, dict) else None
        if not isinstance(fields, list):
            raise CRMError(NormalizedCRMErrorCode.VALIDATION_ERROR, "Salesforce describe response is invalid")
        definitions: list[CRMFieldDefinition] = []
        for item in fields:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            definitions.append(
                CRMFieldDefinition(
                    api_name=str(item["name"]),
                    label=str(item.get("label") or item["name"]),
                    data_type=str(item.get("type") or "unknown"),
                    required=not bool(item.get("nillable", True))
                    and not bool(item.get("defaultedOnCreate", False)),
                    nullable=bool(item.get("nillable", True)),
                    read_only=not bool(item.get("createable", False) or item.get("updateable", False)),
                    unique=bool(item.get("unique", False) or item.get("externalId", False)),
                    custom=bool(item.get("custom", False)),
                    max_length=int(item["length"]) if isinstance(item.get("length"), int) else None,
                    picklist_values=tuple(
                        str(option.get("value"))
                        for option in item.get("picklistValues", [])
                        if isinstance(option, dict) and option.get("active", True)
                    ),
                )
            )
        return definitions

    async def create_lead(
        self, context: CRMConnectionContext, payload: dict[str, Any], *, idempotency_key: str
    ) -> CRMDeliveryResult:
        response = await self._request(context, "POST", "sobjects/Lead", payload=payload)
        body = response.json()
        record_id = body.get("id") if isinstance(body, dict) else None
        return CRMDeliveryResult(
            True, CRMOperation.CREATE, str(record_id) if record_id else None, response.status_code
        )

    async def update_lead(
        self,
        context: CRMConnectionContext,
        external_id: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> CRMDeliveryResult:
        response = await self._request(
            context, "PATCH", f"sobjects/Lead/{quote(external_id, safe='')}", payload=payload
        )
        return CRMDeliveryResult(True, CRMOperation.UPDATE, external_id, response.status_code)

    async def upsert_lead(
        self, context: CRMConnectionContext, payload: dict[str, Any], *, idempotency_key: str
    ) -> CRMDeliveryResult:
        external_field = str(context.configuration.get("externalIdField") or "")
        if external_field and payload.get(external_field) is not None:
            external_value = quote(str(payload[external_field]), safe="")
            response = await self._request(
                context,
                "PATCH",
                f"sobjects/Lead/{quote(external_field, safe='')}/{external_value}",
                payload=payload,
            )
            location = response.headers.get("Location", "")
            record_id = location.rstrip("/").split("/")[-1] or None
            return CRMDeliveryResult(True, CRMOperation.UPSERT, record_id, response.status_code)
        created = await self.create_lead(context, payload, idempotency_key=idempotency_key)
        return CRMDeliveryResult(True, CRMOperation.UPSERT, created.external_record_id, created.http_status)

    async def get_lead(self, context: CRMConnectionContext, external_id: str) -> dict[str, Any]:
        response = await self._request(context, "GET", f"sobjects/Lead/{quote(external_id, safe='')}")
        body = response.json()
        if not isinstance(body, dict):
            raise CRMError(
                NormalizedCRMErrorCode.VALIDATION_ERROR, "Salesforce read-back response is invalid"
            )
        return body


class HubSpotConnector(OAuthJSONConnector):
    provider = CRMProvider.HUBSPOT
    capabilities = CRMCapabilities(
        oauth=True,
        schema_discovery=True,
        create=True,
        update=True,
        upsert=True,
        read_back=True,
        inbound_webhooks=True,
    )
    authorize_url = "https://app.hubspot.com/oauth/authorize"
    oauth_endpoint = "https://api.hubapi.com/oauth/2026-03/token"
    default_scopes = ("crm.objects.contacts.read", "crm.objects.contacts.write", "crm.schemas.contacts.read")

    def _base_url(self, context: CRMConnectionContext, credentials: dict[str, Any]) -> str:
        return str(context.configuration.get("apiDomain") or "https://api.hubapi.com")

    def _object_type(self, context: CRMConnectionContext) -> str:
        return str(context.configuration.get("objectType") or "contacts")

    async def _health_request(self, context: CRMConnectionContext) -> None:
        await self._request(context, "GET", f"crm/v3/properties/{quote(self._object_type(context), safe='')}")

    async def discover_schema(
        self, context: CRMConnectionContext, object_name: str = "contacts"
    ) -> list[CRMFieldDefinition]:
        object_type = self._object_type(context) if object_name == "Leads" else object_name
        response = await self._request(context, "GET", f"crm/v3/properties/{quote(object_type, safe='')}")
        body = response.json()
        results = body.get("results") if isinstance(body, dict) else None
        if not isinstance(results, list):
            raise CRMError(NormalizedCRMErrorCode.VALIDATION_ERROR, "HubSpot properties response is invalid")
        definitions: list[CRMFieldDefinition] = []
        for item in results:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            modification = item.get("modificationMetadata")
            read_only = bool(modification.get("readOnlyValue")) if isinstance(modification, dict) else False
            definitions.append(
                CRMFieldDefinition(
                    api_name=str(item["name"]),
                    label=str(item.get("label") or item["name"]),
                    data_type=str(item.get("type") or item.get("fieldType") or "unknown"),
                    read_only=read_only,
                    unique=bool(item.get("hasUniqueValue", False)),
                    custom=not bool(item.get("hubspotDefined", False)),
                    picklist_values=tuple(
                        str(option.get("value"))
                        for option in item.get("options", [])
                        if isinstance(option, dict) and not option.get("hidden", False)
                    ),
                )
            )
        return definitions

    async def create_lead(
        self, context: CRMConnectionContext, payload: dict[str, Any], *, idempotency_key: str
    ) -> CRMDeliveryResult:
        response = await self._request(
            context,
            "POST",
            f"crm/v3/objects/{quote(self._object_type(context), safe='')}",
            payload={"properties": payload},
        )
        body = response.json()
        record_id = body.get("id") if isinstance(body, dict) else None
        return CRMDeliveryResult(
            True, CRMOperation.CREATE, str(record_id) if record_id else None, response.status_code
        )

    async def update_lead(
        self,
        context: CRMConnectionContext,
        external_id: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> CRMDeliveryResult:
        response = await self._request(
            context,
            "PATCH",
            f"crm/v3/objects/{quote(self._object_type(context), safe='')}/{quote(external_id, safe='')}",
            payload={"properties": payload},
        )
        return CRMDeliveryResult(True, CRMOperation.UPDATE, external_id, response.status_code)

    async def upsert_lead(
        self, context: CRMConnectionContext, payload: dict[str, Any], *, idempotency_key: str
    ) -> CRMDeliveryResult:
        unique_field = str(context.configuration.get("uniqueField") or "email")
        unique_value = payload.get(unique_field)
        if unique_value:
            response = await self._request(
                context,
                "POST",
                f"crm/v3/objects/{quote(self._object_type(context), safe='')}/search",
                payload={
                    "filterGroups": [
                        {
                            "filters": [
                                {"propertyName": unique_field, "operator": "EQ", "value": str(unique_value)}
                            ]
                        }
                    ],
                    "limit": 1,
                },
            )
            body = response.json()
            results = body.get("results") if isinstance(body, dict) else None
            if (
                isinstance(results, list)
                and results
                and isinstance(results[0], dict)
                and results[0].get("id")
            ):
                updated = await self.update_lead(
                    context, str(results[0]["id"]), payload, idempotency_key=idempotency_key
                )
                return CRMDeliveryResult(
                    True, CRMOperation.UPSERT, updated.external_record_id, updated.http_status
                )
        created = await self.create_lead(context, payload, idempotency_key=idempotency_key)
        return CRMDeliveryResult(True, CRMOperation.UPSERT, created.external_record_id, created.http_status)

    async def get_lead(self, context: CRMConnectionContext, external_id: str) -> dict[str, Any]:
        response = await self._request(
            context,
            "GET",
            f"crm/v3/objects/{quote(self._object_type(context), safe='')}/{quote(external_id, safe='')}",
        )
        body = response.json()
        if not isinstance(body, dict):
            raise CRMError(NormalizedCRMErrorCode.VALIDATION_ERROR, "HubSpot read-back response is invalid")
        return body


class Dynamics365Connector(OAuthJSONConnector):
    provider = CRMProvider.DYNAMICS365
    capabilities = CRMCapabilities(
        oauth=True,
        schema_discovery=True,
        create=True,
        update=True,
        upsert=True,
        read_back=True,
        inbound_webhooks=True,
    )

    def _tenant_id(self, context: CRMConnectionContext) -> str:
        return str(context.configuration.get("azureTenantId") or "common")

    def _authorization_endpoint(self, context: CRMConnectionContext) -> str:
        return str(
            context.configuration.get("authorizationUrl")
            or f"https://login.microsoftonline.com/{self._tenant_id(context)}/oauth2/v2.0/authorize"
        )

    def _token_endpoint(self, context: CRMConnectionContext) -> str:
        return str(
            context.configuration.get("tokenUrl")
            or f"https://login.microsoftonline.com/{self._tenant_id(context)}/oauth2/v2.0/token"
        )

    def _scopes(self, context: CRMConnectionContext) -> list[str]:
        configured = context.configuration.get("oauthScopes")
        if isinstance(configured, list) and configured:
            return [str(item) for item in configured]
        resource = str(context.configuration.get("resourceUrl") or "").rstrip("/")
        if not resource:
            raise CRMError(NormalizedCRMErrorCode.CONFIGURATION_ERROR, "Dynamics resourceUrl is required")
        return [f"{resource}/user_impersonation", "offline_access"]

    def _base_url(self, context: CRMConnectionContext, credentials: dict[str, Any]) -> str:
        resource = str(context.configuration.get("resourceUrl") or "").rstrip("/")
        if not resource:
            raise CRMError(NormalizedCRMErrorCode.CONFIGURATION_ERROR, "Dynamics resourceUrl is required")
        return f"{resource}/api/data/{str(context.configuration.get('apiVersion') or 'v9.2')}"

    async def _health_request(self, context: CRMConnectionContext) -> None:
        await self._request(context, "GET", "WhoAmI")

    async def discover_schema(
        self, context: CRMConnectionContext, object_name: str = "lead"
    ) -> list[CRMFieldDefinition]:
        logical = "lead" if object_name.lower() in {"lead", "leads"} else object_name
        response = await self._request(
            context,
            "GET",
            f"EntityDefinitions(LogicalName='{quote(logical, safe='')}')/Attributes",
            params={
                "$select": "LogicalName,DisplayName,AttributeType,IsValidForCreate,IsValidForUpdate,MaxLength,IsCustomAttribute,RequiredLevel"
            },
        )
        body = response.json()
        values = body.get("value") if isinstance(body, dict) else None
        if not isinstance(values, list):
            raise CRMError(NormalizedCRMErrorCode.VALIDATION_ERROR, "Dynamics metadata response is invalid")
        definitions: list[CRMFieldDefinition] = []
        for item in values:
            if not isinstance(item, dict) or not item.get("LogicalName"):
                continue
            display_name = item.get("DisplayName")
            label = None
            if isinstance(display_name, dict):
                localized = display_name.get("UserLocalizedLabel")
                if isinstance(localized, dict):
                    label = localized.get("Label")
            required_level = item.get("RequiredLevel")
            required = (
                isinstance(required_level, dict) and required_level.get("Value") == "ApplicationRequired"
            )
            definitions.append(
                CRMFieldDefinition(
                    api_name=str(item["LogicalName"]),
                    label=str(label or item["LogicalName"]),
                    data_type=str(item.get("AttributeType") or "unknown"),
                    required=required,
                    nullable=not required,
                    read_only=not bool(item.get("IsValidForCreate") or item.get("IsValidForUpdate")),
                    custom=bool(item.get("IsCustomAttribute", False)),
                    max_length=int(item["MaxLength"]) if isinstance(item.get("MaxLength"), int) else None,
                )
            )
        return definitions

    async def create_lead(
        self, context: CRMConnectionContext, payload: dict[str, Any], *, idempotency_key: str
    ) -> CRMDeliveryResult:
        response = await self._request(context, "POST", "leads", payload=payload)
        entity_id = response.headers.get("OData-EntityId", "").rstrip(")").split("(")[-1] or None
        return CRMDeliveryResult(True, CRMOperation.CREATE, entity_id, response.status_code)

    async def update_lead(
        self,
        context: CRMConnectionContext,
        external_id: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> CRMDeliveryResult:
        response = await self._request(
            context, "PATCH", f"leads({quote(external_id, safe='')})", payload=payload
        )
        return CRMDeliveryResult(True, CRMOperation.UPDATE, external_id, response.status_code)

    async def upsert_lead(
        self, context: CRMConnectionContext, payload: dict[str, Any], *, idempotency_key: str
    ) -> CRMDeliveryResult:
        expression = str(context.configuration.get("alternateKeyExpression") or "")
        if expression:
            try:
                target = expression.format(**payload)
            except KeyError as exc:
                raise CRMError(
                    NormalizedCRMErrorCode.MAPPING_ERROR, "Dynamics alternate key field is missing"
                ) from exc
            response = await self._request(context, "PATCH", f"leads({target})", payload=payload)
            entity_id = response.headers.get("OData-EntityId", "").rstrip(")").split("(")[-1] or None
            return CRMDeliveryResult(True, CRMOperation.UPSERT, entity_id, response.status_code)
        created = await self.create_lead(context, payload, idempotency_key=idempotency_key)
        return CRMDeliveryResult(True, CRMOperation.UPSERT, created.external_record_id, created.http_status)

    async def get_lead(self, context: CRMConnectionContext, external_id: str) -> dict[str, Any]:
        response = await self._request(context, "GET", f"leads({quote(external_id, safe='')})")
        body = response.json()
        if not isinstance(body, dict):
            raise CRMError(NormalizedCRMErrorCode.VALIDATION_ERROR, "Dynamics read-back response is invalid")
        return body


class PipedriveConnector(OAuthJSONConnector):
    provider = CRMProvider.PIPEDRIVE
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
    authorize_url = "https://oauth.pipedrive.com/oauth/authorize"
    oauth_endpoint = "https://oauth.pipedrive.com/oauth/token"

    def _base_url(self, context: CRMConnectionContext, credentials: dict[str, Any]) -> str:
        return str(
            credentials.get("api_domain")
            or context.configuration.get("apiDomain")
            or "https://api.pipedrive.com"
        )

    async def _health_request(self, context: CRMConnectionContext) -> None:
        await self._request(context, "GET", "v1/users/me")

    async def discover_schema(
        self, context: CRMConnectionContext, object_name: str = "Leads"
    ) -> list[CRMFieldDefinition]:
        response = await self._request(context, "GET", "v1/leadFields")
        body = response.json()
        values = body.get("data") if isinstance(body, dict) else None
        if not isinstance(values, list):
            raise CRMError(
                NormalizedCRMErrorCode.VALIDATION_ERROR, "Pipedrive lead fields response is invalid"
            )
        return [
            CRMFieldDefinition(
                api_name=str(item["key"]),
                label=str(item.get("name") or item["key"]),
                data_type=str(item.get("field_type") or "unknown"),
                read_only=not bool(item.get("edit_flag", True)),
                custom=bool(item.get("id"))
                and str(item.get("key")) not in {"id", "title", "owner_id", "person_id", "organization_id"},
            )
            for item in values
            if isinstance(item, dict) and item.get("key")
        ]

    async def create_lead(
        self, context: CRMConnectionContext, payload: dict[str, Any], *, idempotency_key: str
    ) -> CRMDeliveryResult:
        response = await self._request(context, "POST", "v1/leads", payload=payload)
        body = response.json()
        data = body.get("data") if isinstance(body, dict) else None
        record_id = data.get("id") if isinstance(data, dict) else None
        return CRMDeliveryResult(
            True, CRMOperation.CREATE, str(record_id) if record_id else None, response.status_code
        )

    async def update_lead(
        self,
        context: CRMConnectionContext,
        external_id: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> CRMDeliveryResult:
        response = await self._request(
            context, "PATCH", f"v1/leads/{quote(external_id, safe='')}", payload=payload
        )
        return CRMDeliveryResult(True, CRMOperation.UPDATE, external_id, response.status_code)

    async def upsert_lead(
        self, context: CRMConnectionContext, payload: dict[str, Any], *, idempotency_key: str
    ) -> CRMDeliveryResult:
        working = dict(payload)
        record_id = working.pop("id", None)
        if record_id:
            updated = await self.update_lead(
                context, str(record_id), working, idempotency_key=idempotency_key
            )
            return CRMDeliveryResult(
                True, CRMOperation.UPSERT, updated.external_record_id, updated.http_status
            )
        created = await self.create_lead(context, working, idempotency_key=idempotency_key)
        return CRMDeliveryResult(True, CRMOperation.UPSERT, created.external_record_id, created.http_status)

    async def get_lead(self, context: CRMConnectionContext, external_id: str) -> dict[str, Any]:
        response = await self._request(context, "GET", f"v1/leads/{quote(external_id, safe='')}")
        body = response.json()
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict):
            raise CRMError(NormalizedCRMErrorCode.VALIDATION_ERROR, "Pipedrive read-back response is invalid")
        return data


class FreshsalesConnector(CRMConnector):
    provider = CRMProvider.FRESHSALES
    capabilities = CRMCapabilities(
        schema_discovery=True, create=True, update=True, upsert=True, read_back=True
    )

    def _base_url(self, context: CRMConnectionContext) -> str:
        base = str(context.configuration.get("baseUrl") or "").rstrip("/")
        if not base.startswith("https://"):
            raise CRMError(NormalizedCRMErrorCode.CONFIGURATION_ERROR, "Freshsales baseUrl must use HTTPS")
        return base

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
            async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
                response = await client.request(
                    method,
                    f"{self._base_url(context)}/{path.lstrip('/')}",
                    params=params,
                    json=payload,
                    headers={
                        "Authorization": f"Token token={api_key}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                )
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
        if response.status_code == 429:
            raise CRMError(
                NormalizedCRMErrorCode.RATE_LIMIT_ERROR,
                "Freshsales rate limit reached",
                retryable=True,
                http_status=429,
            )
        if response.status_code in {401, 403}:
            raise CRMError(
                NormalizedCRMErrorCode.AUTHENTICATION_ERROR,
                "Freshsales authorization failed",
                requires_reconnect=True,
                http_status=response.status_code,
            )
        if response.status_code >= 500:
            raise CRMError(
                NormalizedCRMErrorCode.PROVIDER_UNAVAILABLE,
                "Freshsales is temporarily unavailable",
                retryable=True,
                http_status=response.status_code,
            )
        raise CRMError(
            NormalizedCRMErrorCode.VALIDATION_ERROR,
            "Freshsales rejected the request",
            http_status=response.status_code,
        )

    async def health_check(self, context: CRMConnectionContext) -> CRMHealthResult:
        started = time.monotonic()
        try:
            await self._request(context, "GET", "api/users/me")
            return CRMHealthResult(
                IntegrationHealthStatus.HEALTHY,
                {"credentials": "up", "api": "up"},
                int((time.monotonic() - started) * 1000),
            )
        except CRMError as exc:
            return CRMHealthResult(
                IntegrationHealthStatus.AUTH_REQUIRED
                if exc.requires_reconnect
                else IntegrationHealthStatus.UNHEALTHY,
                {"credentials": "down" if exc.requires_reconnect else "unknown", "api": "down"},
                int((time.monotonic() - started) * 1000),
                {"error": exc.code.value},
            )

    async def discover_schema(
        self, context: CRMConnectionContext, object_name: str = "contacts"
    ) -> list[CRMFieldDefinition]:
        response = await self._request(context, "GET", "api/settings/contacts/fields")
        body = response.json()
        values = body.get("fields") if isinstance(body, dict) else None
        if not isinstance(values, list):
            raise CRMError(
                NormalizedCRMErrorCode.VALIDATION_ERROR, "Freshsales field metadata response is invalid"
            )
        return [
            CRMFieldDefinition(
                api_name=str(item.get("name") or item.get("label")),
                label=str(item.get("label") or item.get("name")),
                data_type=str(item.get("type") or "unknown"),
                required=bool(item.get("required", False)),
                nullable=not bool(item.get("required", False)),
                read_only=bool(item.get("read_only", False)),
                custom=bool(item.get("custom_field", False)),
            )
            for item in values
            if isinstance(item, dict) and (item.get("name") or item.get("label"))
        ]

    async def create_lead(
        self, context: CRMConnectionContext, payload: dict[str, Any], *, idempotency_key: str
    ) -> CRMDeliveryResult:
        response = await self._request(context, "POST", "api/contacts", payload={"contact": payload})
        body = response.json()
        contact = body.get("contact") if isinstance(body, dict) else None
        record_id = contact.get("id") if isinstance(contact, dict) else None
        return CRMDeliveryResult(
            True, CRMOperation.CREATE, str(record_id) if record_id else None, response.status_code
        )

    async def update_lead(
        self,
        context: CRMConnectionContext,
        external_id: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> CRMDeliveryResult:
        response = await self._request(
            context, "PUT", f"api/contacts/{quote(external_id, safe='')}", payload={"contact": payload}
        )
        return CRMDeliveryResult(True, CRMOperation.UPDATE, external_id, response.status_code)

    async def upsert_lead(
        self, context: CRMConnectionContext, payload: dict[str, Any], *, idempotency_key: str
    ) -> CRMDeliveryResult:
        email = payload.get("email")
        if email:
            response = await self._request(
                context, "GET", "api/contacts/lookup", params={"email": str(email)}
            )
            body = response.json()
            contact = body.get("contact") if isinstance(body, dict) else None
            if isinstance(contact, dict) and contact.get("id"):
                updated = await self.update_lead(
                    context, str(contact["id"]), payload, idempotency_key=idempotency_key
                )
                return CRMDeliveryResult(
                    True, CRMOperation.UPSERT, updated.external_record_id, updated.http_status
                )
        created = await self.create_lead(context, payload, idempotency_key=idempotency_key)
        return CRMDeliveryResult(True, CRMOperation.UPSERT, created.external_record_id, created.http_status)

    async def get_lead(self, context: CRMConnectionContext, external_id: str) -> dict[str, Any]:
        response = await self._request(context, "GET", f"api/contacts/{quote(external_id, safe='')}")
        body = response.json()
        contact = body.get("contact") if isinstance(body, dict) else None
        if not isinstance(contact, dict):
            raise CRMError(
                NormalizedCRMErrorCode.VALIDATION_ERROR, "Freshsales read-back response is invalid"
            )
        return contact
