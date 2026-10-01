from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.lead_crm.domain import CRMConnectionStatus
from northstar_api.lead_crm.models import CRMFieldMapping, CRMRoute
from northstar_api.lead_crm.workspace_scope import WorkspaceCRMRoute
from northstar_api.services.zoho_one_click_connection import workspace_zoho_connection
from northstar_api.zoho_platform import ZohoPlatformConfiguration


async def zoho_connection_status(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    platform: ZohoPlatformConfiguration | None,
) -> dict[str, Any]:
    current = await workspace_zoho_connection(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    if current is None:
        return {
            "platformConfigured": platform is not None,
            "connected": False,
            "status": "not_connected",
            "connectionId": None,
            "connectionName": None,
            "autoSyncNewLeads": False,
            "autoSyncUpdates": False,
            "mappingReady": False,
            "routeReady": False,
            "liveCertification": None,
            "missingConfiguration": []
            if platform is not None
            else ["ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET"],
        }

    connection, scope = current
    mapping = await session.scalar(
        select(CRMFieldMapping).where(
            CRMFieldMapping.tenant_id == tenant_id,
            CRMFieldMapping.connection_id == connection.id,
            CRMFieldMapping.object_name == "Leads",
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
    connection_text = str(connection.id)
    route_ready = any(
        route.enabled
        and connection_text
        in {str(item) for item in (route.actions_json or {}).get("connectionIds", [])}
        for route in routes
    )
    certification = (connection.configuration_json or {}).get("liveCertification")
    return {
        "platformConfigured": platform is not None,
        "connected": connection.status == CRMConnectionStatus.HEALTHY.value,
        "status": connection.status,
        "connectionId": str(connection.id),
        "connectionName": connection.name,
        "autoSyncNewLeads": scope.auto_sync_new_leads,
        "autoSyncUpdates": scope.auto_sync_updates,
        "mappingReady": bool(mapping and mapping.status == "active"),
        "mappingVersion": mapping.version if mapping else None,
        "routeReady": route_ready,
        "lastHealthAt": connection.last_health_at.isoformat() if connection.last_health_at else None,
        "lastSuccessAt": connection.last_success_at.isoformat() if connection.last_success_at else None,
        "lastError": connection.last_error,
        "liveCertification": certification if isinstance(certification, dict) else None,
        "missingConfiguration": []
        if platform is not None
        else ["ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET"],
    }
