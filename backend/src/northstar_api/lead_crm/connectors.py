from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from northstar_api.lead_crm.domain import (
    CRMOperation,
    CRMProvider,
    IntegrationHealthStatus,
    NormalizedCRMErrorCode,
)


@dataclass(frozen=True, slots=True)
class CRMCapabilities:
    oauth: bool = False
    schema_discovery: bool = False
    create: bool = True
    update: bool = True
    upsert: bool = False
    read_back: bool = False
    inbound_webhooks: bool = False
    webhook_management: bool = False


@dataclass(frozen=True, slots=True)
class CRMConnectionContext:
    tenant_id: UUID
    connection_id: UUID
    provider: CRMProvider
    configuration: dict[str, Any]
    credentials: dict[str, Any] = field(repr=False)


@dataclass(frozen=True, slots=True)
class CRMFieldDefinition:
    api_name: str
    label: str
    data_type: str
    required: bool = False
    nullable: bool = True
    read_only: bool = False
    unique: bool = False
    custom: bool = False
    max_length: int | None = None
    picklist_values: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CRMHealthResult:
    status: IntegrationHealthStatus
    checks: dict[str, str]
    latency_ms: int | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CRMDeliveryResult:
    accepted: bool
    operation: CRMOperation
    external_record_id: str | None = None
    http_status: int | None = None
    provider_code: str | None = None
    provider_request_id: str | None = None
    retry_after_seconds: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class CRMError(RuntimeError):
    def __init__(
        self,
        code: NormalizedCRMErrorCode,
        message: str,
        *,
        retryable: bool = False,
        requires_reconnect: bool = False,
        http_status: int | None = None,
        provider_code: str | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.requires_reconnect = requires_reconnect
        self.http_status = http_status
        self.provider_code = provider_code
        self.retry_after_seconds = retry_after_seconds


class CRMConnector(ABC):
    provider: CRMProvider
    capabilities: CRMCapabilities

    async def authenticate(self, context: CRMConnectionContext) -> None:
        """Validate existing credentials if a provider requires a separate check."""
        return None

    def build_authorization_url(
        self,
        context: CRMConnectionContext,
        *,
        redirect_uri: str,
        state: str,
        code_challenge: str | None = None,
    ) -> str:
        raise CRMError(NormalizedCRMErrorCode.CONFIGURATION_ERROR, "OAuth authorization is not supported")

    async def exchange_authorization_code(
        self,
        context: CRMConnectionContext,
        *,
        code: str,
        redirect_uri: str,
        code_verifier: str | None = None,
    ) -> dict[str, Any]:
        raise CRMError(NormalizedCRMErrorCode.CONFIGURATION_ERROR, "OAuth authorization is not supported")

    async def refresh_credentials(self, context: CRMConnectionContext) -> dict[str, Any]:
        raise CRMError(NormalizedCRMErrorCode.CONFIGURATION_ERROR, "Credential refresh is not supported")

    @abstractmethod
    async def health_check(self, context: CRMConnectionContext) -> CRMHealthResult:
        raise NotImplementedError

    async def discover_schema(
        self, context: CRMConnectionContext, object_name: str = "Leads"
    ) -> list[CRMFieldDefinition]:
        raise CRMError(NormalizedCRMErrorCode.CONFIGURATION_ERROR, "Schema discovery is not supported")

    async def validate_mapping(self, fields: list[CRMFieldDefinition], mapping: dict[str, Any]) -> list[str]:
        known = {field.api_name for field in fields if not field.read_only}
        return [target for target in mapping.values() if isinstance(target, str) and target not in known]

    async def search_record(
        self, context: CRMConnectionContext, criteria: dict[str, Any]
    ) -> dict[str, Any] | None:
        raise CRMError(NormalizedCRMErrorCode.CONFIGURATION_ERROR, "Record search is not supported")

    @abstractmethod
    async def create_lead(
        self, context: CRMConnectionContext, payload: dict[str, Any], *, idempotency_key: str
    ) -> CRMDeliveryResult:
        raise NotImplementedError

    async def update_lead(
        self,
        context: CRMConnectionContext,
        external_id: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> CRMDeliveryResult:
        raise CRMError(NormalizedCRMErrorCode.CONFIGURATION_ERROR, "Lead update is not supported")

    async def upsert_lead(
        self, context: CRMConnectionContext, payload: dict[str, Any], *, idempotency_key: str
    ) -> CRMDeliveryResult:
        if not self.capabilities.upsert:
            return await self.create_lead(context, payload, idempotency_key=idempotency_key)
        raise NotImplementedError

    async def get_lead(self, context: CRMConnectionContext, external_id: str) -> dict[str, Any]:
        raise CRMError(NormalizedCRMErrorCode.CONFIGURATION_ERROR, "Read-back verification is not supported")

    async def register_webhook(
        self, context: CRMConnectionContext, configuration: dict[str, Any]
    ) -> dict[str, Any]:
        raise CRMError(NormalizedCRMErrorCode.CONFIGURATION_ERROR, "Webhook management is not supported")

    async def unregister_webhook(self, context: CRMConnectionContext, webhook_id: str) -> None:
        raise CRMError(NormalizedCRMErrorCode.CONFIGURATION_ERROR, "Webhook management is not supported")


class CRMRegistry:
    def __init__(self) -> None:
        self._connectors: dict[CRMProvider, CRMConnector] = {}
        self._defaults_loaded = False

    def _ensure_defaults(self) -> None:
        if self._defaults_loaded:
            return
        self._defaults_loaded = True
        from northstar_api.lead_crm.providers import register_default_connectors

        register_default_connectors()

    def register(self, connector: CRMConnector) -> None:
        if connector.provider in self._connectors:
            raise ValueError(f"CRM connector already registered: {connector.provider.value}")
        self._connectors[connector.provider] = connector

    def get(self, provider: CRMProvider) -> CRMConnector:
        self._ensure_defaults()
        try:
            return self._connectors[provider]
        except KeyError as exc:
            raise CRMError(
                NormalizedCRMErrorCode.CONFIGURATION_ERROR,
                f"CRM connector is not registered: {provider.value}",
            ) from exc

    def providers(self) -> tuple[CRMProvider, ...]:
        self._ensure_defaults()
        return tuple(self._connectors)


crm_registry = CRMRegistry()
