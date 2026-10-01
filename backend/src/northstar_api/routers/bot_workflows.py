from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.agent_purpose import get_agent_purpose
from northstar_api.bot_workflow_schemas import BotWorkflowOut, BotWorkflowSave, BotWorkflowTemplateOut
from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.models import Agent, BotWorkflow
from northstar_api.security import Principal
from northstar_api.services.bot_workflow_templates import template, template_catalog

router = APIRouter(prefix="/bot-workflows", tags=["bot workflows"])
DB = Annotated[AsyncSession, Depends(get_session)]
ViewPrincipal = Annotated[Principal, Depends(require_permissions("agents.view"))]
UpdatePrincipal = Annotated[Principal, Depends(require_permissions("agents.update"))]


def output(workflow: BotWorkflow) -> BotWorkflowOut:
    return BotWorkflowOut(
        id=workflow.id, agent_id=workflow.agent_id, name=workflow.name,
        purpose=workflow.purpose, status=workflow.status, steps=workflow.steps_json or [],
        created_at=workflow.created_at, updated_at=workflow.updated_at,
    )


async def _save(agent: Agent, payload: BotWorkflowSave, principal: Principal, session: AsyncSession) -> BotWorkflow:
    purpose = await get_agent_purpose(
        session, tenant_id=principal.tenant_id, workspace_id=principal.workspace_id, agent_id=agent.id
    )
    if payload.purpose != purpose:
        raise HTTPException(status_code=409, detail="Workflow purpose must match the selected bot purpose")
    workflow = await session.scalar(select(BotWorkflow).where(BotWorkflow.agent_id == agent.id).with_for_update())
    if not workflow:
        workflow = BotWorkflow(tenant_id=principal.tenant_id, workspace_id=principal.workspace_id, agent_id=agent.id)
        session.add(workflow)
    workflow.name = payload.name.strip()
    workflow.purpose = payload.purpose.value
    workflow.status = payload.status
    workflow.steps_json = [step.model_dump(mode="json", by_alias=True) for step in payload.steps]
    await session.commit()
    await session.refresh(workflow)
    return workflow


@router.get("", response_model=list[BotWorkflowOut])
async def list_workflows(principal: ViewPrincipal, session: DB) -> list[BotWorkflowOut]:
    rows = (await session.scalars(select(BotWorkflow).where(
        BotWorkflow.tenant_id == principal.tenant_id,
        BotWorkflow.workspace_id == principal.workspace_id,
        *((BotWorkflow.agent_id.in_(principal.agent_ids),) if principal.agent_ids is not None else ()),
    ).order_by(BotWorkflow.updated_at.desc()))).all()
    return [output(row) for row in rows]


@router.get("/templates", response_model=list[BotWorkflowTemplateOut])
async def list_templates(principal: ViewPrincipal) -> list[BotWorkflowTemplateOut]:
    del principal
    return [BotWorkflowTemplateOut.model_validate(item) for item in template_catalog()]


@router.post("/{agent_id}/templates/{template_key}", response_model=BotWorkflowOut)
async def apply_template(
    agent_id: UUID, template_key: str, principal: UpdatePrincipal, session: DB
) -> BotWorkflowOut:
    preset = template(template_key)
    if preset is None:
        raise HTTPException(status_code=404, detail="Workflow template not found")
    agent = await session.scalar(select(Agent).where(
        Agent.id == agent_id, Agent.tenant_id == principal.tenant_id,
        Agent.workspace_id == principal.workspace_id,
        *((Agent.id.in_(principal.agent_ids),) if principal.agent_ids is not None else ()),
    ))
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return output(await _save(agent, preset, principal, session))


@router.get("/{agent_id}", response_model=BotWorkflowOut)
async def get_workflow(agent_id: UUID, principal: ViewPrincipal, session: DB) -> BotWorkflowOut:
    workflow = await session.scalar(select(BotWorkflow).where(
        BotWorkflow.agent_id == agent_id, BotWorkflow.tenant_id == principal.tenant_id,
        BotWorkflow.workspace_id == principal.workspace_id,
        *((BotWorkflow.agent_id.in_(principal.agent_ids),) if principal.agent_ids is not None else ()),
    ))
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return output(workflow)


@router.put("/{agent_id}", response_model=BotWorkflowOut)
async def save_workflow(agent_id: UUID, payload: BotWorkflowSave, principal: UpdatePrincipal, session: DB) -> BotWorkflowOut:
    agent = await session.scalar(select(Agent).where(
        Agent.id == agent_id, Agent.tenant_id == principal.tenant_id,
        Agent.workspace_id == principal.workspace_id,
        *((Agent.id.in_(principal.agent_ids),) if principal.agent_ids is not None else ()),
    ))
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return output(await _save(agent, payload, principal, session))


@router.delete("/{agent_id}", status_code=204)
async def delete_workflow(agent_id: UUID, principal: UpdatePrincipal, session: DB) -> Response:
    workflow = await session.scalar(select(BotWorkflow).where(
        BotWorkflow.agent_id == agent_id, BotWorkflow.tenant_id == principal.tenant_id,
        BotWorkflow.workspace_id == principal.workspace_id,
    ).with_for_update())
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    await session.delete(workflow)
    await session.commit()
    return Response(status_code=204)
