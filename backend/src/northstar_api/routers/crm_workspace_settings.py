from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.lead_crm.api_schemas import (
    CRMWorkspaceSettingsOut,
    CRMWorkspaceSettingsPatch,
)
from northstar_api.lead_crm.audit import record_audit_event
from northstar_api.lead_crm.workspace_scope import WorkspaceCRMConnection
from northstar_api.security import Principal

router = APIRouter(tags=["crm"])
DB = Annotated[AsyncSession, Depends(get_session)]
CRMViewPrincipal = Annotated[Principal, Depends(require_permissions("crm.view"))]
CRMManagePrincipal = Annotated[Principal, Depends(require_permissions("crm.manage"))]


async def _workspace_binding(
    session: AsyncSession,
    principal: Principal,
    connection_id: UUID,
) -> WorkspaceCRMConnection | None:
    return await session.scalar(
        select(WorkspaceCRMConnection).where(
            WorkspaceCRMConnection.connection_id == connection_id,
            WorkspaceCRMConnection.tenant_id == principal.tenant_id,
            WorkspaceCRMConnection.workspace_id == principal.workspace_id,
        )
    )


def _settings_out(binding: WorkspaceCRMConnection) -> CRMWorkspaceSettingsOut:
    return CRMWorkspaceSettingsOut(
        connection_id=binding.connection_id,
        auto_sync_new_leads=binding.auto_sync_new_leads,
        auto_sync_updates=binding.auto_sync_updates,
        updated_at=binding.updated_at,
    )


@router.get(
    "/crm/connections/{connection_id}/workspace-settings",
    response_model=CRMWorkspaceSettingsOut,
)
async def get_crm_workspace_settings(
    connection_id: UUID,
    principal: CRMViewPrincipal,
    session: DB,
) -> CRMWorkspaceSettingsOut:
    binding = await _workspace_binding(session, principal, connection_id)
    if not binding:
        raise HTTPException(status_code=404, detail="CRM connection not found in this workspace")
    return _settings_out(binding)


@router.patch(
    "/crm/connections/{connection_id}/workspace-settings",
    response_model=CRMWorkspaceSettingsOut,
)
async def update_crm_workspace_settings(
    connection_id: UUID,
    payload: CRMWorkspaceSettingsPatch,
    principal: CRMManagePrincipal,
    session: DB,
) -> CRMWorkspaceSettingsOut:
    if payload.auto_sync_new_leads is None and payload.auto_sync_updates is None:
        raise HTTPException(status_code=400, detail="At least one CRM auto-sync setting is required")

    binding = await _workspace_binding(session, principal, connection_id)
    if not binding:
        raise HTTPException(status_code=404, detail="CRM connection not found in this workspace")

    before = {
        "autoSyncNewLeads": binding.auto_sync_new_leads,
        "autoSyncUpdates": binding.auto_sync_updates,
    }
    if payload.auto_sync_new_leads is not None:
        binding.auto_sync_new_leads = payload.auto_sync_new_leads
    if payload.auto_sync_updates is not None:
        binding.auto_sync_updates = payload.auto_sync_updates

    record_audit_event(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id,
        action="crm.workspace_settings.updated",
        entity_type="crm_connection",
        entity_id=str(connection_id),
        category="crm",
        before=before,
        after={
            "autoSyncNewLeads": binding.auto_sync_new_leads,
            "autoSyncUpdates": binding.auto_sync_updates,
        },
    )
    await session.commit()
    await session.refresh(binding)
    return _settings_out(binding)
