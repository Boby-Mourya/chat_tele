from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.lead_crm.crm_workflow_schemas import CRMWorkflowOut
from northstar_api.security import Principal
from northstar_api.services.crm_workflow import crm_workflow_service

router = APIRouter(prefix="/crm", tags=["crm workflow"])
DB = Annotated[AsyncSession, Depends(get_session)]
CRMWorkflowPrincipal = Annotated[
    Principal,
    Depends(require_permissions("crm.view")),
]


@router.get("/workflow", response_model=CRMWorkflowOut)
async def get_crm_workflow(
    principal: CRMWorkflowPrincipal,
    session: DB,
    limit: int = Query(default=25, ge=1, le=100),
) -> CRMWorkflowOut:
    """Return the live workspace-scoped Lead-to-CRM workflow and readiness state."""

    assert principal.workspace_id is not None
    return await crm_workflow_service.build(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        allowed_agent_ids=principal.agent_ids,
        limit=limit,
    )
