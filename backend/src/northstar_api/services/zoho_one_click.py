from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.lead_crm.audit import record_integration_audit
from northstar_api.lead_crm.connectors import CRMError, crm_registry
from northstar_api.lead_crm.domain import (
    CRMConnectionStatus,
    CRMProvider,
    IntegrationHealthStatus,
    NormalizedCRMErrorCode,
)
from northstar_api.lead_crm.models import CRMConnection, IntegrationHealthSnapshot
from northstar_api.services.zoho_one_click_certification import certify_live_zoho
from northstar_api.services.zoho_one_click_common import (
    ZohoBootstrapResult,
    ZohoOneClickError,
    decrypt_zoho_credentials,
    zoho_connection_context,
)
from northstar_api.services.zoho_one_click_connection import (
    ensure_workspace_zoho_connection,
    ensure_zoho_route,
    workspace_zoho_connection,
)
from northstar_api.services.zoho_one_click_mapping import (
    build_default_zoho_mapping,
    persist_zoho_mapping,
    persist_zoho_schema,
    schema_hash,
)
from northstar_api.zoho_platform import ZohoPlatformConfiguration


async def bootstrap_zoho_connection(
    session: AsyncSession,
    *,
    connection: CRMConnection,
    workspace_id: UUID,
    actor_user_id: UUID,
    platform: ZohoPlatformConfiguration,
) -> ZohoBootstrapResult:
    connector = crm_registry.get(CRMProvider.ZOHO)
    credentials = decrypt_zoho_credentials(connection)
    context = zoho_connection_context(connection, credentials)
    now = datetime.now(UTC)

    health = await connector.health_check(context)
    session.add(
        IntegrationHealthSnapshot(
            tenant_id=connection.tenant_id,
            connection_id=connection.id,
            status=health.status.value,
            checks_json=dict(health.checks),
            latency_ms=health.latency_ms,
        )
    )
    connection.last_health_at = now
    if health.status is not IntegrationHealthStatus.HEALTHY:
        connection.status = health.status.value
        connection.last_failure_at = now
        connection.last_error = str(health.details.get("error") or "Zoho health check failed")[:1000]
        raise ZohoOneClickError("Zoho authorization succeeded but the CRM health check failed")

    fields = await connector.discover_schema(context, "Leads")
    if not fields:
        raise ZohoOneClickError("Zoho returned no Leads field metadata")
    current_schema_hash = schema_hash(fields)
    await persist_zoho_schema(
        session,
        connection=connection,
        fields=fields,
        current_schema_hash=current_schema_hash,
    )
    certification_email = f"northstar.crm.cert.{connection.id.hex[:12]}@example.com"
    definition, unsupported_required = build_default_zoho_mapping(
        fields,
        certification_email=certification_email,
    )
    invalid_targets = await connector.validate_mapping(fields, definition["fields"])
    mapping = await persist_zoho_mapping(
        session,
        connection=connection,
        definition=definition,
        current_schema_hash=current_schema_hash,
        invalid_targets=invalid_targets,
        unsupported_required=unsupported_required,
    )
    if invalid_targets or unsupported_required:
        message = (
            "Zoho Leads contains required fields that cannot be configured automatically: "
            + ", ".join(unsupported_required or invalid_targets)
        )[:1000]
        connection.status = CRMConnectionStatus.CONFIGURATION_ERROR.value
        connection.last_failure_at = now
        connection.last_error = message
        raise ZohoOneClickError(message)

    route = await ensure_zoho_route(
        session,
        connection=connection,
        workspace_id=workspace_id,
        enabled=True,
    )
    certification: dict[str, Any]
    if platform.live_certification_enabled:
        certification = await certify_live_zoho(
            connection,
            credentials=credentials,
            definition=definition,
        )
    else:
        certification = {
            "status": "skipped",
            "verifiedFields": [],
            "verifiedAt": None,
            "reason": "ZOHO_LIVE_CERTIFICATION_ENABLED is false",
        }

    connection.configuration_json = {
        **dict(connection.configuration_json or {}),
        "managedBy": "zoho-one-click",
        "schemaHash": current_schema_hash,
        "mappingId": str(mapping.id),
        "routeId": str(route.id),
        "liveCertification": certification,
    }
    connection.status = CRMConnectionStatus.HEALTHY.value
    connection.last_success_at = datetime.now(UTC)
    connection.last_error = None
    record_integration_audit(
        session,
        tenant_id=connection.tenant_id,
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        action="crm.zoho.one_click.certified",
        entity_type="crm_connection",
        entity_id=str(connection.id),
        after={
            "status": connection.status,
            "mappingId": str(mapping.id),
            "routeId": str(route.id),
            "liveCertification": certification,
        },
    )
    await session.flush()
    return ZohoBootstrapResult(
        connection_id=connection.id,
        mapping_id=mapping.id,
        route_id=route.id,
        external_record_id=certification.get("externalRecordId"),
        certification_status=str(certification.get("status") or "unknown"),
        verified_fields=tuple(str(item) for item in certification.get("verifiedFields") or []),
    )


def normalized_failure_status(exc: Exception) -> str:
    if isinstance(exc, CRMError):
        if exc.requires_reconnect:
            return CRMConnectionStatus.AUTH_REQUIRED.value
        if exc.code is NormalizedCRMErrorCode.RATE_LIMIT_ERROR:
            return CRMConnectionStatus.RATE_LIMITED.value
        if exc.code is NormalizedCRMErrorCode.CONFIGURATION_ERROR:
            return CRMConnectionStatus.CONFIGURATION_ERROR.value
    return CRMConnectionStatus.DEGRADED.value


__all__ = [
    "ZohoBootstrapResult",
    "ZohoOneClickError",
    "bootstrap_zoho_connection",
    "build_default_zoho_mapping",
    "ensure_workspace_zoho_connection",
    "normalized_failure_status",
    "workspace_zoho_connection",
]
