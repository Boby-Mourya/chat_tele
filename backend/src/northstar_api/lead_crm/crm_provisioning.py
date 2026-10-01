from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import SecretStr
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.config import Settings, get_settings
from northstar_api.lead_crm.connectors import (
    CRMCapabilities,
    CRMConnectionContext,
    CRMError,
    CRMFieldDefinition,
    crm_registry,
)
from northstar_api.lead_crm.credentials import credential_store
from northstar_api.lead_crm.domain import CRMConnectionStatus, CRMDeliveryStatus, CRMProvider
from northstar_api.lead_crm.models import (
    CRMConnection,
    CRMDelivery,
    CRMFieldMapping,
    CRMFieldSchema,
    CRMRoute,
)
from northstar_api.lead_crm.workspace_scope import WorkspaceCRMConnection, WorkspaceCRMRoute
from northstar_api.models import Lead
from northstar_api.services.outbox import enqueue_event

MANAGED_OAUTH_PROVIDERS = frozenset(
    {
        CRMProvider.ZOHO,
        CRMProvider.SALESFORCE,
        CRMProvider.HUBSPOT,
        CRMProvider.DYNAMICS365,
        CRMProvider.PIPEDRIVE,
    }
)
DIRECT_CONNECT_PROVIDERS = frozenset({CRMProvider.FRESHSALES, CRMProvider.GENERIC_REST})
ONE_CLICK_PROVIDERS = MANAGED_OAUTH_PROVIDERS | DIRECT_CONNECT_PROVIDERS

PROVIDER_NAMES: dict[CRMProvider, str] = {
    CRMProvider.ZOHO: "Zoho CRM",
    CRMProvider.SALESFORCE: "Salesforce",
    CRMProvider.HUBSPOT: "HubSpot",
    CRMProvider.DYNAMICS365: "Microsoft Dynamics 365",
    CRMProvider.PIPEDRIVE: "Pipedrive",
    CRMProvider.FRESHSALES: "Freshsales",
    CRMProvider.GENERIC_REST: "Generic REST CRM",
    CRMProvider.GENERIC_WEBHOOK: "Generic CRM webhook",
}

_ZOHO_ACCOUNTS_BY_REGION = {
    "us": "https://accounts.zoho.com",
    "eu": "https://accounts.zoho.eu",
    "in": "https://accounts.zoho.in",
    "au": "https://accounts.zoho.com.au",
    "jp": "https://accounts.zoho.jp",
    "ca": "https://accounts.zohocloud.ca",
    "sa": "https://accounts.zoho.sa",
    "cn": "https://accounts.zoho.com.cn",
}

_PROVIDER_CREDENTIAL_SETTINGS: dict[CRMProvider, tuple[str, str]] = {
    CRMProvider.ZOHO: ("crm_zoho_client_id", "crm_zoho_client_secret"),
    CRMProvider.SALESFORCE: ("crm_salesforce_client_id", "crm_salesforce_client_secret"),
    CRMProvider.HUBSPOT: ("crm_hubspot_client_id", "crm_hubspot_client_secret"),
    CRMProvider.DYNAMICS365: ("crm_dynamics365_client_id", "crm_dynamics365_client_secret"),
    CRMProvider.PIPEDRIVE: ("crm_pipedrive_client_id", "crm_pipedrive_client_secret"),
}


@dataclass(frozen=True, slots=True)
class CRMReadiness:
    connection_id: UUID
    provider: str
    status: str
    ready: bool
    live_certified: bool
    blockers: tuple[str, ...]
    schema_hash: str | None
    mapping_version: int | None
    route_id: UUID | None
    auto_sync_new_leads: bool
    auto_sync_updates: bool
    event_pipeline_ready: bool
    verified_delivery_id: UUID | None = None
    external_record_id: str | None = None
    certified_at: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "connectionId": str(self.connection_id),
            "provider": self.provider,
            "status": self.status,
            "ready": self.ready,
            "liveCertified": self.live_certified,
            "blockers": list(self.blockers),
            "schemaHash": self.schema_hash,
            "mappingVersion": self.mapping_version,
            "routeId": str(self.route_id) if self.route_id else None,
            "autoSyncNewLeads": self.auto_sync_new_leads,
            "autoSyncUpdates": self.auto_sync_updates,
            "eventPipelineReady": self.event_pipeline_ready,
            "verifiedDeliveryId": str(self.verified_delivery_id) if self.verified_delivery_id else None,
            "externalRecordId": self.external_record_id,
            "certifiedAt": self.certified_at,
        }


@dataclass(frozen=True, slots=True)
class CRMProvisioningResult:
    connection: CRMConnection
    readiness: CRMReadiness
    schema_field_count: int


def _secret_value(value: object) -> str:
    if isinstance(value, SecretStr):
        return value.get_secret_value().strip()
    return str(value or "").strip()


def managed_oauth_credentials(
    provider: CRMProvider,
    settings: Settings | None = None,
) -> dict[str, str]:
    if provider not in MANAGED_OAUTH_PROVIDERS:
        raise ValueError(f"{provider.value} does not support managed OAuth")
    active = settings or get_settings()
    client_field, secret_field = _PROVIDER_CREDENTIAL_SETTINGS[provider]
    client_id = _secret_value(getattr(active, client_field, None))
    client_secret = _secret_value(getattr(active, secret_field, None))
    if not client_id or not client_secret:
        raise ValueError(f"Managed OAuth is not configured for {provider.value}")
    return {"client_id": client_id, "client_secret": client_secret}


def managed_oauth_is_configured(provider: CRMProvider, settings: Settings | None = None) -> bool:
    try:
        managed_oauth_credentials(provider, settings)
    except ValueError:
        return False
    return True


def managed_provider_catalog(settings: Settings | None = None) -> list[dict[str, Any]]:
    active = settings or get_settings()
    values: list[dict[str, Any]] = []
    for provider in sorted(ONE_CLICK_PROVIDERS, key=lambda item: item.value):
        if provider in MANAGED_OAUTH_PROVIDERS:
            mode = "oauth"
            configured = managed_oauth_is_configured(provider, active)
            required = ["resourceUrl"] if provider == CRMProvider.DYNAMICS365 else []
        elif provider == CRMProvider.FRESHSALES:
            mode = "api_key"
            configured = True
            required = ["baseUrl", "apiKey"]
        else:
            mode = "rest"
            configured = True
            required = ["baseUrl", "upsertPath", "getPath", "externalIdPath"]
        values.append(
            {
                "id": provider.value,
                "name": PROVIDER_NAMES[provider],
                "mode": mode,
                "configured": configured,
                "requiredInputs": required,
                "supportsSandbox": provider == CRMProvider.SALESFORCE,
                "supportsReadBack": crm_registry.get(provider).capabilities.read_back,
            }
        )
    return values


def one_click_configuration(
    provider: CRMProvider,
    *,
    environment: str,
    region: str | None,
    resource_url: str | None,
    azure_tenant_id: str | None,
) -> dict[str, Any]:
    configuration: dict[str, Any] = {"managedOAuth": True}
    if provider == CRMProvider.ZOHO:
        normalized_region = (region or "us").strip().lower()
        if normalized_region not in _ZOHO_ACCOUNTS_BY_REGION:
            raise ValueError("Unsupported Zoho data-center region")
        configuration.update(
            {
                "accountsUrl": _ZOHO_ACCOUNTS_BY_REGION[normalized_region],
                "apiVersion": "v8",
                "oauthScopes": [
                    "ZohoCRM.modules.leads.ALL",
                    "ZohoCRM.settings.fields.READ",
                    "ZohoCRM.settings.modules.READ",
                    "ZohoCRM.org.READ",
                ],
                "defaultCompany": "Individual",
            }
        )
    elif provider == CRMProvider.SALESFORCE:
        configuration.update({"environment": environment, "apiVersion": "v65.0", "pkce": True})
    elif provider == CRMProvider.HUBSPOT:
        configuration.update({"objectType": "contacts", "uniqueField": "email"})
    elif provider == CRMProvider.DYNAMICS365:
        normalized = str(resource_url or "").strip().rstrip("/")
        if not normalized.startswith("https://"):
            raise ValueError("Dynamics resourceUrl must be a public HTTPS URL")
        configuration.update(
            {
                "resourceUrl": normalized,
                "azureTenantId": (azure_tenant_id or "common").strip() or "common",
                "apiVersion": "v9.2",
                "pkce": True,
            }
        )
    elif provider == CRMProvider.PIPEDRIVE:
        configuration.update({"apiDomain": "https://api.pipedrive.com"})
    else:
        raise ValueError(f"{provider.value} does not support managed OAuth")
    return configuration


def _field_payload(field: CRMFieldDefinition) -> dict[str, Any]:
    return {
        "apiName": field.api_name,
        "label": field.label,
        "dataType": field.data_type,
        "required": field.required,
        "nullable": field.nullable,
        "readOnly": field.read_only,
        "unique": field.unique,
        "custom": field.custom,
        "maxLength": field.max_length,
        "picklistValues": list(field.picklist_values),
        "metadata": field.metadata,
    }


def _schema_hash(definitions: Iterable[CRMFieldDefinition]) -> str:
    serialized = [_field_payload(item) for item in definitions]
    raw = json.dumps(serialized, separators=(",", ":"), sort_keys=True, default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def _candidate_rules(provider: CRMProvider) -> list[dict[str, Any]]:
    if provider == CRMProvider.ZOHO:
        return [
            {"source": "firstName", "target": "First_Name"},
            {"source": "lastName", "target": "Last_Name", "default": "Unknown"},
            {"source": "email", "target": "Email", "transform": "lower"},
            {"source": "phone", "target": "Mobile"},
            {"source": "company", "target": "Company", "default": "Individual"},
            {"source": "jobTitle", "target": "Designation"},
            {"source": "qualificationReason", "target": "Description"},
            {"source": "source.channel", "target": "Lead_Source"},
        ]
    if provider == CRMProvider.SALESFORCE:
        return [
            {"source": "firstName", "target": "FirstName"},
            {"source": "lastName", "target": "LastName", "default": "Unknown"},
            {"source": "email", "target": "Email", "transform": "lower"},
            {"source": "phone", "target": "Phone"},
            {"source": "company", "target": "Company", "default": "Individual"},
            {"source": "jobTitle", "target": "Title"},
            {"source": "qualificationReason", "target": "Description"},
            {"source": "source.channel", "target": "LeadSource"},
        ]
    if provider == CRMProvider.HUBSPOT:
        return [
            {"source": "firstName", "target": "firstname"},
            {"source": "lastName", "target": "lastname"},
            {"source": "email", "target": "email", "transform": "lower"},
            {"source": "phone", "target": "phone"},
            {"source": "company", "target": "company"},
            {"source": "jobTitle", "target": "jobtitle"},
            {"source": "source.channel", "target": "hs_analytics_source"},
        ]
    if provider == CRMProvider.DYNAMICS365:
        return [
            {"source": "name", "target": "subject", "default": "Northstar lead"},
            {"source": "firstName", "target": "firstname"},
            {"source": "lastName", "target": "lastname", "default": "Unknown"},
            {"source": "email", "target": "emailaddress1", "transform": "lower"},
            {"source": "phone", "target": "telephone1"},
            {"source": "company", "target": "companyname"},
            {"source": "jobTitle", "target": "jobtitle"},
            {"source": "qualificationReason", "target": "description"},
        ]
    if provider == CRMProvider.PIPEDRIVE:
        return [{"source": "name", "target": "title", "default": "Northstar lead"}]
    if provider == CRMProvider.FRESHSALES:
        return [
            {"source": "firstName", "target": "first_name"},
            {"source": "lastName", "target": "last_name", "default": "Unknown"},
            {"source": "email", "target": "email", "transform": "lower"},
            {"source": "phone", "target": "mobile_number"},
            {"source": "jobTitle", "target": "job_title"},
        ]
    if provider in {CRMProvider.GENERIC_REST, CRMProvider.GENERIC_WEBHOOK}:
        return [
            {"source": "publicId", "target": "external_id"},
            {"source": "name", "target": "name"},
            {"source": "firstName", "target": "first_name"},
            {"source": "lastName", "target": "last_name"},
            {"source": "email", "target": "email", "transform": "lower"},
            {"source": "phone", "target": "phone"},
            {"source": "company", "target": "company"},
            {"source": "jobTitle", "target": "job_title"},
            {"source": "status", "target": "status"},
            {"source": "qualificationScore", "target": "qualification_score"},
            {"source": "source.channel", "target": "source_channel"},
        ]
    return []


def build_default_mapping(
    provider: CRMProvider,
    definitions: Iterable[CRMFieldDefinition],
) -> tuple[dict[str, Any], dict[str, Any]]:
    values = list(definitions)
    writable = {item.api_name for item in values if not item.read_only}
    required = {item.api_name for item in values if item.required and not item.read_only}
    candidates = _candidate_rules(provider)
    rules = (
        candidates
        if provider in {CRMProvider.GENERIC_REST, CRMProvider.GENERIC_WEBHOOK}
        else [rule for rule in candidates if str(rule["target"]) in writable]
    )
    targets = {str(rule["target"]) for rule in rules}

    # Zoho's runtime supplies safe values for the standard mandatory Lead fields.
    provider_supplied: set[str] = set()
    if provider == CRMProvider.ZOHO:
        provider_supplied = {"Last_Name", "Company"} & writable

    missing_required = sorted(required - targets - provider_supplied)
    mapping = {"fields": rules}
    validation = {
        "valid": not missing_required,
        "unknownOrReadOnlyTargets": [],
        "missingRequiredTargets": missing_required,
        "generated": True,
        "provider": provider.value,
    }
    return mapping, validation


async def _ensure_workspace_binding(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    connection_id: UUID,
) -> WorkspaceCRMConnection:
    binding = await session.scalar(
        select(WorkspaceCRMConnection).where(
            WorkspaceCRMConnection.tenant_id == tenant_id,
            WorkspaceCRMConnection.workspace_id == workspace_id,
            WorkspaceCRMConnection.connection_id == connection_id,
        )
    )
    if binding is None:
        binding = WorkspaceCRMConnection(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            connection_id=connection_id,
            auto_sync_new_leads=True,
            auto_sync_updates=True,
        )
        session.add(binding)
    else:
        binding.auto_sync_new_leads = True
        binding.auto_sync_updates = True
    return binding


async def _ensure_route(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    connection: CRMConnection,
) -> CRMRoute:
    routes = list(
        await session.scalars(
            select(CRMRoute)
            .join(WorkspaceCRMRoute, WorkspaceCRMRoute.route_id == CRMRoute.id)
            .where(
                CRMRoute.tenant_id == tenant_id,
                WorkspaceCRMRoute.tenant_id == tenant_id,
                WorkspaceCRMRoute.workspace_id == workspace_id,
            )
            .order_by(CRMRoute.priority, CRMRoute.created_at)
        )
    )
    for route in routes:
        raw_ids = (route.actions_json or {}).get("connectionIds", [])
        if str(connection.id) in {str(item) for item in raw_ids}:
            route.enabled = True
            return route

    route = CRMRoute(
        tenant_id=tenant_id,
        name=f"Auto sync {connection.provider} {str(connection.id)[:8]}",
        enabled=True,
        priority=100,
        conditions_json={},
        actions_json={"connectionIds": [str(connection.id)]},
    )
    session.add(route)
    await session.flush()
    session.add(
        WorkspaceCRMRoute(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            route_id=route.id,
        )
    )
    return route


async def ensure_managed_oauth_connection(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    provider: CRMProvider,
    display_name: str | None,
    environment: str,
    region: str | None,
    configuration: dict[str, Any],
    settings: Settings | None = None,
    client_credentials: dict[str, str] | None = None,
) -> CRMConnection:
    if provider not in MANAGED_OAUTH_PROVIDERS:
        raise ValueError("Provider does not support one-click OAuth")
    scoped = list(
        await session.scalars(
            select(CRMConnection)
            .join(WorkspaceCRMConnection, WorkspaceCRMConnection.connection_id == CRMConnection.id)
            .where(
                CRMConnection.tenant_id == tenant_id,
                CRMConnection.provider == provider.value,
                WorkspaceCRMConnection.tenant_id == tenant_id,
                WorkspaceCRMConnection.workspace_id == workspace_id,
            )
            .order_by(CRMConnection.created_at.desc())
        )
    )
    connection = next(
        (
            item
            for item in scoped
            if bool((item.configuration_json or {}).get("managedOAuth"))
            and item.status != CRMConnectionStatus.DISABLED.value
        ),
        None,
    )
    previous = (
        credential_store.decrypt(connection.credentials_encrypted)
        if connection is not None and connection.credentials_encrypted
        else {}
    )
    customer_app = bool(client_credentials) or bool(
        connection is not None and (connection.configuration_json or {}).get("credentialSource") == "customer"
    )
    managed_credentials = client_credentials or (
        {key: previous.get(key, "") for key in ("client_id", "client_secret")}
        if customer_app
        else managed_oauth_credentials(provider, settings)
    )
    if not all(managed_credentials.get(key) for key in ("client_id", "client_secret")):
        raise ValueError("OAuth client ID and client secret are required")
    configuration = {**configuration, "credentialSource": "customer" if customer_app else "platform"}
    stored_credentials: dict[str, Any] = dict(managed_credentials)
    if connection is None:
        base_name = (display_name or PROVIDER_NAMES[provider]).strip()[:160]
        stored_name = base_name
        conflict = await session.scalar(
            select(CRMConnection.id).where(
                CRMConnection.tenant_id == tenant_id,
                CRMConnection.name == stored_name,
            )
        )
        if conflict:
            stored_name = f"{base_name[:130]} [{str(workspace_id)[:8]}-{uuid4().hex[:8]}]"
        capabilities: CRMCapabilities = crm_registry.get(provider).capabilities
        connection = CRMConnection(
            tenant_id=tenant_id,
            provider=provider.value,
            name=stored_name,
            environment=environment,
            region=region,
            status=CRMConnectionStatus.DRAFT.value,
            configuration_json=dict(configuration),
            capabilities_json={
                "oauth": capabilities.oauth,
                "schemaDiscovery": capabilities.schema_discovery,
                "create": capabilities.create,
                "update": capabilities.update,
                "upsert": capabilities.upsert,
                "readBack": capabilities.read_back,
                "inboundWebhooks": capabilities.inbound_webhooks,
                "webhookManagement": capabilities.webhook_management,
                "managedOAuth": True,
            },
        )
        session.add(connection)
        await session.flush()
    else:
        if (
            all(previous.get(key) == managed_credentials.get(key) for key in ("client_id", "client_secret"))
            and connection.environment == environment
            and connection.region == region
            and (connection.configuration_json or {}).get("resourceUrl") == configuration.get("resourceUrl")
        ):
            stored_credentials.update(previous)
        stored_credentials.update(managed_credentials)
        connection.environment = environment
        connection.region = region
        connection.configuration_json = {**dict(connection.configuration_json or {}), **configuration}
        connection.status = CRMConnectionStatus.DRAFT.value
        connection.last_error = None

    connection.credentials_encrypted = credential_store.encrypt(stored_credentials)
    await _ensure_workspace_binding(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        connection_id=connection.id,
    )
    await _ensure_route(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        connection=connection,
    )
    await session.flush()
    return connection


async def ensure_direct_connection(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    provider: CRMProvider,
    display_name: str | None,
    configuration: dict[str, Any],
    credentials: dict[str, Any],
) -> CRMConnection:
    if provider not in DIRECT_CONNECT_PROVIDERS:
        raise ValueError("Provider does not support direct one-step connection")
    connection = await session.scalar(
        select(CRMConnection)
        .join(WorkspaceCRMConnection, WorkspaceCRMConnection.connection_id == CRMConnection.id)
        .where(
            CRMConnection.tenant_id == tenant_id,
            CRMConnection.provider == provider.value,
            WorkspaceCRMConnection.tenant_id == tenant_id,
            WorkspaceCRMConnection.workspace_id == workspace_id,
            CRMConnection.status != CRMConnectionStatus.DISABLED.value,
        )
        .order_by(CRMConnection.created_at.desc())
    )
    encrypted = credential_store.encrypt(credentials)
    if connection is None:
        base_name = (display_name or PROVIDER_NAMES[provider]).strip()[:160]
        stored_name = base_name
        conflict = await session.scalar(
            select(CRMConnection.id).where(
                CRMConnection.tenant_id == tenant_id,
                CRMConnection.name == stored_name,
            )
        )
        if conflict:
            stored_name = f"{base_name[:140]} [{str(workspace_id)[:8]}]"
        capabilities = crm_registry.get(provider).capabilities
        connection = CRMConnection(
            tenant_id=tenant_id,
            provider=provider.value,
            name=stored_name,
            environment="production",
            status=CRMConnectionStatus.CONNECTING.value,
            credentials_encrypted=encrypted,
            configuration_json={**configuration, "directConnect": True},
            capabilities_json={
                "oauth": capabilities.oauth,
                "schemaDiscovery": capabilities.schema_discovery,
                "create": capabilities.create,
                "update": capabilities.update,
                "upsert": capabilities.upsert,
                "readBack": capabilities.read_back,
                "inboundWebhooks": capabilities.inbound_webhooks,
                "webhookManagement": capabilities.webhook_management,
                "directConnect": True,
            },
        )
        session.add(connection)
        await session.flush()
    else:
        connection.credentials_encrypted = encrypted
        connection.configuration_json = {
            **dict(connection.configuration_json or {}),
            **configuration,
            "directConnect": True,
        }
        connection.status = CRMConnectionStatus.CONNECTING.value
        connection.last_error = None
    await _ensure_workspace_binding(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        connection_id=connection.id,
    )
    await _ensure_route(session, tenant_id=tenant_id, workspace_id=workspace_id, connection=connection)
    await session.flush()
    return connection


async def provision_connection(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    connection: CRMConnection,
    credentials: dict[str, Any],
) -> CRMProvisioningResult:
    try:
        provider = CRMProvider(connection.provider)
        connector = crm_registry.get(provider)
    except (ValueError, CRMError) as exc:
        raise ValueError("CRM connector is unavailable") from exc

    context = CRMConnectionContext(
        tenant_id=tenant_id,
        connection_id=connection.id,
        provider=provider,
        configuration=dict(connection.configuration_json or {}),
        credentials=dict(credentials),
    )
    definitions: list[CRMFieldDefinition] = []
    if connector.capabilities.schema_discovery:
        definitions = await connector.discover_schema(context, "Leads")
        if not definitions:
            raise ValueError("CRM returned no writable Lead schema")
    digest = _schema_hash(definitions)
    await session.execute(
        delete(CRMFieldSchema).where(
            CRMFieldSchema.tenant_id == tenant_id,
            CRMFieldSchema.connection_id == connection.id,
            CRMFieldSchema.object_name == "Leads",
        )
    )
    for field in definitions:
        session.add(
            CRMFieldSchema(
                tenant_id=tenant_id,
                connection_id=connection.id,
                object_name="Leads",
                api_name=field.api_name,
                display_label=field.label,
                data_type=field.data_type,
                required=field.required,
                nullable=field.nullable,
                read_only=field.read_only,
                unique=field.unique,
                custom=field.custom,
                max_length=field.max_length,
                picklist_json={"values": list(field.picklist_values)},
                metadata_json=dict(field.metadata),
                schema_hash=digest,
            )
        )

    mapping_definition, validation = build_default_mapping(provider, definitions)
    mapping = await session.scalar(
        select(CRMFieldMapping).where(
            CRMFieldMapping.tenant_id == tenant_id,
            CRMFieldMapping.connection_id == connection.id,
            CRMFieldMapping.object_name == "Leads",
        )
    )
    if mapping is None:
        mapping = CRMFieldMapping(
            tenant_id=tenant_id,
            connection_id=connection.id,
            object_name="Leads",
            version=1,
            status="active" if validation["valid"] else "degraded",
            mapping_json=mapping_definition,
            validation_json={**validation, "schemaHash": digest, "workspaceId": str(workspace_id)},
            schema_hash=digest,
        )
        session.add(mapping)
    else:
        if mapping.mapping_json != mapping_definition or mapping.schema_hash != digest:
            mapping.version += 1
        mapping.mapping_json = mapping_definition
        mapping.validation_json = {**validation, "schemaHash": digest, "workspaceId": str(workspace_id)}
        mapping.schema_hash = digest
        mapping.status = "active" if validation["valid"] else "degraded"

    await _ensure_workspace_binding(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        connection_id=connection.id,
    )
    await _ensure_route(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        connection=connection,
    )
    if validation["valid"]:
        connection.status = CRMConnectionStatus.HEALTHY.value
        connection.last_error = None
        connection.last_success_at = datetime.now(UTC)
        enqueue_event(
            session,
            tenant_id=tenant_id,
            aggregate_type="crm_connection",
            aggregate_id=connection.id,
            event_type="crm.connection.backfill.requested.v1",
            payload={
                "workspaceId": str(workspace_id),
                "connectionId": str(connection.id),
                "batchSize": 100,
            },
        )
    else:
        connection.status = CRMConnectionStatus.CONFIGURATION_ERROR.value
        missing = ", ".join(validation["missingRequiredTargets"])
        connection.last_error = f"Required CRM fields need mapping: {missing}"[:1000]
        connection.last_failure_at = datetime.now(UTC)
    await session.flush()
    readiness = await connection_readiness(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        connection=connection,
    )
    return CRMProvisioningResult(
        connection=connection,
        readiness=readiness,
        schema_field_count=len(definitions),
    )


async def connection_readiness(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    connection: CRMConnection,
) -> CRMReadiness:
    binding = await session.scalar(
        select(WorkspaceCRMConnection).where(
            WorkspaceCRMConnection.tenant_id == tenant_id,
            WorkspaceCRMConnection.workspace_id == workspace_id,
            WorkspaceCRMConnection.connection_id == connection.id,
        )
    )
    mapping = await session.scalar(
        select(CRMFieldMapping).where(
            CRMFieldMapping.tenant_id == tenant_id,
            CRMFieldMapping.connection_id == connection.id,
            CRMFieldMapping.object_name == "Leads",
        )
    )
    schema = await session.scalar(
        select(CRMFieldSchema).where(
            CRMFieldSchema.tenant_id == tenant_id,
            CRMFieldSchema.connection_id == connection.id,
            CRMFieldSchema.object_name == "Leads",
        )
    )
    routes = list(
        await session.scalars(
            select(CRMRoute)
            .join(WorkspaceCRMRoute, WorkspaceCRMRoute.route_id == CRMRoute.id)
            .where(
                CRMRoute.tenant_id == tenant_id,
                WorkspaceCRMRoute.tenant_id == tenant_id,
                WorkspaceCRMRoute.workspace_id == workspace_id,
            )
        )
    )
    route = next(
        (
            item
            for item in routes
            if item.enabled
            and str(connection.id) in {str(raw) for raw in (item.actions_json or {}).get("connectionIds", [])}
        ),
        None,
    )
    verified = await session.scalar(
        select(CRMDelivery)
        .join(Lead, Lead.id == CRMDelivery.lead_id)
        .where(
            CRMDelivery.tenant_id == tenant_id,
            CRMDelivery.connection_id == connection.id,
            CRMDelivery.status == CRMDeliveryStatus.VERIFIED.value,
            CRMDelivery.external_record_id.is_not(None),
            Lead.tenant_id == tenant_id,
            Lead.workspace_id == workspace_id,
        )
        .order_by(CRMDelivery.verified_at.desc(), CRMDelivery.updated_at.desc())
    )

    settings = get_settings()
    event_pipeline_ready = bool(settings.kafka_enabled and settings.background_dispatch_enabled)
    blockers: list[str] = []
    if not connection.credentials_encrypted and not connection.credentials_ref:
        blockers.append("credentials_missing")
    if connection.status != CRMConnectionStatus.HEALTHY.value:
        blockers.append("connection_not_healthy")
    if (
        connection.provider
        not in {
            CRMProvider.GENERIC_REST.value,
            CRMProvider.GENERIC_WEBHOOK.value,
        }
        and schema is None
    ):
        blockers.append("schema_not_discovered")
    if mapping is None or mapping.status != "active":
        blockers.append("mapping_not_active")
    if route is None:
        blockers.append("route_not_enabled")
    if binding is None or not binding.auto_sync_new_leads:
        blockers.append("auto_sync_new_leads_disabled")
    if binding is None or not binding.auto_sync_updates:
        blockers.append("auto_sync_updates_disabled")
    if not event_pipeline_ready:
        blockers.append("event_pipeline_not_enabled")

    return CRMReadiness(
        connection_id=connection.id,
        provider=connection.provider,
        status=connection.status,
        ready=not blockers,
        live_certified=verified is not None,
        blockers=tuple(blockers),
        schema_hash=mapping.schema_hash if mapping else (schema.schema_hash if schema else None),
        mapping_version=mapping.version if mapping else None,
        route_id=route.id if route else None,
        auto_sync_new_leads=bool(binding and binding.auto_sync_new_leads),
        auto_sync_updates=bool(binding and binding.auto_sync_updates),
        event_pipeline_ready=event_pipeline_ready,
        verified_delivery_id=verified.id if verified else None,
        external_record_id=verified.external_record_id if verified else None,
        certified_at=verified.verified_at if verified else None,
    )
