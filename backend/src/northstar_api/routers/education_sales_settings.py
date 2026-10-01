from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.models import Workspace
from northstar_api.schemas import APIModel
from northstar_api.security import Principal

router = APIRouter(prefix="/education/settings/sales-routing", tags=["education"])
DB = Annotated[AsyncSession, Depends(get_session)]
WorkspaceViewPrincipal = Annotated[Principal, Depends(require_permissions("workspace.view"))]
WorkspaceUpdatePrincipal = Annotated[Principal, Depends(require_permissions("workspace.update"))]
_SETTINGS_KEY = "educationSales"


class EducationSalesRoutingSettings(APIModel):
    create_upsell_leads: bool = False


async def _workspace(principal: Principal, session: AsyncSession) -> Workspace:
    if principal.workspace_id is None:
        raise HTTPException(status_code=403, detail="Workspace access is unavailable")
    workspace = await session.scalar(
        select(Workspace).where(
            Workspace.id == principal.workspace_id,
            Workspace.tenant_id == principal.tenant_id,
        )
    )
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


def education_sales_settings(workspace: Workspace) -> EducationSalesRoutingSettings:
    return EducationSalesRoutingSettings(create_upsell_leads=False)


@router.get("", response_model=EducationSalesRoutingSettings)
async def get_education_sales_routing(
    principal: WorkspaceViewPrincipal,
    session: DB,
) -> EducationSalesRoutingSettings:
    workspace = await _workspace(principal, session)
    return education_sales_settings(workspace)


@router.patch("", response_model=EducationSalesRoutingSettings)
async def update_education_sales_routing(
    payload: EducationSalesRoutingSettings,
    principal: WorkspaceUpdatePrincipal,
    session: DB,
) -> EducationSalesRoutingSettings:
    if payload.create_upsell_leads:
        raise HTTPException(status_code=409, detail="Education chats stay separate from leads")
    workspace = await _workspace(principal, session)
    settings = dict(workspace.settings_json or {})
    settings[_SETTINGS_KEY] = payload.model_dump(by_alias=True)
    workspace.settings_json = settings
    await session.commit()
    await session.refresh(workspace)
    return education_sales_settings(workspace)
