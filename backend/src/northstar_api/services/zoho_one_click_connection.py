from __future__ import annotations

from dataclasses import asdict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.lead_crm.audit import record_integration_audit
from northstar_api.lead_crm.connectors import crm_registry
from northstar_api.lead_crm.credentials import credential_store
from northstar_api.lead_crm.domain import CRMConnectionStatus, CRMOperation, CRMProvider
from northstar_api.lead_crm.models import CRMConnection, CRMRoute
from northstar_api.lead_crm.workspace_scope import WorkspaceCRMConnection, WorkspaceCRMRoute
from northstar_api.services.zoho_one_click_common import decrypt_zoho_credentials
from northstar_api.zoho_platform import ZohoPlatformConfiguration


async def workspace_zoho_connection(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
) -> tuple[CRMConnection, WorkspaceCRMConnection] | None:
    rows = (
        await session.execute(
            select(CRMConnection, WorkspaceCRMConnection)
            .join(
                WorkspaceCRMConnection,
                WorkspaceCRMConnection.connection_id == CRMConnection.id,
            )
            .where(
                CRMConnection.tenant_id == tenant_id,
                CRMConnection.provider == CRMProvider.ZOHO.value,
                WorkspaceCRMConnection.tenant_id == tenant_id,
                WorkspaceCRMConnection.workspace_id == workspace_id,
            )
            .order_by(CRMConnection.created_at.desc())
        )
    ).all()
    for connection, scope in rows:
        if (connection.configuration_json or {}).get("managedBy") == "zoho-one-click":
            return connection, scope
    return None


async def ensure_zoho_route(
    session: AsyncSession,
    *,
    connection: CRMConnection,
    workspace_id: UUID,
    enabled: bool,
) -> CRMRoute:
    routes = list(
        await session.scalars(
            select(CRMRoute)
            .join(WorkspaceCRMRoute, WorkspaceCRMRoute.route_id == CRMRoute.id)
            .where(
                CRMRoute.tenant_id == connection.tenant_id,
                WorkspaceCRMRoute.tenant_id == connection.tenant_id,
                WorkspaceCRMRoute.workspace_id == workspace_id,
            )
            .order_by(CRMRoute.priority, CRMRoute.created_at)
        )
    )
    connection_text = str(connection.id)
    for route in routes:
        raw_ids = (route.actions_json or {}).get("connectionIds") or []
        if connection_text in {str(item) for item in raw_ids}:
            route.enabled = enabled
            route.actions_json = {
                **dict(route.actions_json or {}),
                "connectionIds": [connection_text],
                "operation": CRMOperation.UPSERT.value,
                "objectName": "Leads",
                "managedBy": "zoho-one-click",
            }
            return route

    route = CRMRoute(
        tenant_id=connection.tenant_id,
        name=f"Zoho automatic lead route {connection.id.hex[:8]}",
        enabled=enabled,
        priority=10,
        version=1,
        conditions_json={},
        actions_json={
            "connectionIds": [connection_text],
            "operation": CRMOperation.UPSERT.value,
            "objectName": "Leads",
            "managedBy": "zoho-one-click",
        },
    )
    session.add(route)
    await session.flush()
    session.add(
        WorkspaceCRMRoute(
            tenant_id=connection.tenant_id,
            workspace_id=workspace_id,
            route_id=route.id,
        )
    )
    return route


async def ensure_workspace_zoho_connection(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    actor_user_id: UUID,
    platform: ZohoPlatformConfiguration,
) -> tuple[CRMConnection, WorkspaceCRMConnection, CRMRoute]:
    existing = await workspace_zoho_connection(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    connector = crm_registry.get(CRMProvider.ZOHO)
    if existing is None:
        credentials = {
            "client_id": platform.client_id,
            "client_secret": platform.client_secret,
        }
        connection = CRMConnection(
            tenant_id=tenant_id,
            provider=CRMProvider.ZOHO.value,
            name=f"Zoho CRM {workspace_id.hex[:8]}",
            environment="production",
            status=CRMConnectionStatus.CONNECTING.value,
            credentials_encrypted=credential_store.encrypt(credentials),
            configuration_json=platform.provider_configuration(),
            capabilities_json=asdict(connector.capabilities),
        )
        session.add(connection)
        await session.flush()
        scope = WorkspaceCRMConnection(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            connection_id=connection.id,
            auto_sync_new_leads=True,
            auto_sync_updates=True,
        )
        session.add(scope)
        await session.flush()
        action = "crm.zoho.one_click.connection.created"
    else:
        connection, scope = existing
        credentials = decrypt_zoho_credentials(connection)
        credentials.update(
            {
                "client_id": platform.client_id,
                "client_secret": platform.client_secret,
            }
        )
        connection.credentials_encrypted = credential_store.encrypt(credentials)
        connection.configuration_json = {
            **dict(connection.configuration_json or {}),
            **platform.provider_configuration(),
        }
        connection.capabilities_json = asdict(connector.capabilities)
        connection.status = CRMConnectionStatus.CONNECTING.value
        connection.last_error = None
        scope.auto_sync_new_leads = True
        scope.auto_sync_updates = True
        action = "crm.zoho.one_click.connection.reused"

    # Keep the route disabled until OAuth, schema discovery, mapping and the
    # live upsert/read-back certification all succeed.
    route = await ensure_zoho_route(
        session,
        connection=connection,
        workspace_id=workspace_id,
        enabled=False,
    )
    record_integration_audit(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        action=action,
        entity_type="crm_connection",
        entity_id=str(connection.id),
        after={
            "provider": CRMProvider.ZOHO.value,
            "status": connection.status,
            "autoSyncNewLeads": scope.auto_sync_new_leads,
            "autoSyncUpdates": scope.auto_sync_updates,
            "routeId": str(route.id),
        },
    )
    await session.flush()
    return connection, scope, route
