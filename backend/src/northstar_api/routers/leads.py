from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.agent_purpose import AgentPurpose, get_agent_purpose
from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.lead_crm.domain import CRMDeliveryStatus, LeadLifecycleStatus
from northstar_api.lead_crm.models import CRMDelivery, LeadProfile
from northstar_api.lead_crm.services import lead_domain_service
from northstar_api.logging import request_id_ctx
from northstar_api.models import Agent, Conversation, Lead
from northstar_api.schemas import LeadCreate, LeadOut, LeadPatch, PageResult
from northstar_api.security import Principal
from northstar_api.services.education_conversation_policy import education_source
from northstar_api.services.outbox import enqueue_event

router = APIRouter(prefix="/leads", tags=["leads"])
DB = Annotated[AsyncSession, Depends(get_session)]
LeadsViewPrincipal = Annotated[Principal, Depends(require_permissions("leads.view"))]
LeadsUpdatePrincipal = Annotated[Principal, Depends(require_permissions("leads.update"))]
VALID_LEAD_STATUSES = {item.value for item in LeadLifecycleStatus}
VALID_CRM_STATUSES = {item.value for item in CRMDeliveryStatus} | {"not_synced"}


def lead_response(lead: Lead) -> LeadOut:
    return LeadOut(
        id=lead.id,
        workspace_id=lead.workspace_id,
        agent_id=lead.agent_id,
        conversation_id=lead.conversation_id,
        name=lead.name,
        email=lead.email,
        phone=lead.phone,
        status=lead.status,
        consent=lead.consent,
        fields=lead.fields_json,
        created_at=lead.created_at,
        updated_at=lead.updated_at,
    )


def enqueue_crm_sync(session: AsyncSession, lead: Lead, *, reason: str) -> None:
    enqueue_event(
        session,
        tenant_id=lead.tenant_id,
        aggregate_type="lead",
        aggregate_id=lead.id,
        event_type="lead.crm.sync.requested.v1",
        payload={
            "leadId": str(lead.id),
            "workspaceId": str(lead.workspace_id),
            "agentId": str(lead.agent_id),
            "reason": reason,
        },
    )


@router.get("", response_model=PageResult[LeadOut])
async def list_leads(
    principal: LeadsViewPrincipal,
    session: DB,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    search: str | None = Query(default=None, max_length=320),
    status: str | None = Query(default=None, max_length=40),
    agent_id: UUID | None = Query(default=None),
    channel: str | None = Query(default=None, max_length=60),
    crm_status: str | None = Query(default=None, max_length=40),
) -> PageResult[LeadOut]:
    conditions = [
        Lead.tenant_id == principal.tenant_id,
        Lead.workspace_id == principal.workspace_id,
        ~education_source(Lead),
    ]
    if principal.agent_ids is not None:
        conditions.append(Lead.agent_id.in_(principal.agent_ids))
    if status:
        if status not in VALID_LEAD_STATUSES:
            raise HTTPException(status_code=400, detail="Unsupported lead status")
        conditions.append(Lead.status == status)
    if agent_id:
        conditions.append(Lead.agent_id == agent_id)
    if channel:
        conditions.append(
            exists(
                select(LeadProfile.id).where(
                    LeadProfile.tenant_id == principal.tenant_id,
                    LeadProfile.lead_id == Lead.id,
                    LeadProfile.source_channel == channel,
                )
            )
        )
    if crm_status:
        if crm_status not in VALID_CRM_STATUSES:
            raise HTTPException(status_code=400, detail="Unsupported CRM delivery status")
        delivery_exists = exists(
            select(CRMDelivery.id).where(
                CRMDelivery.tenant_id == principal.tenant_id,
                CRMDelivery.lead_id == Lead.id,
            )
        )
        if crm_status == "not_synced":
            conditions.append(~delivery_exists)
        else:
            conditions.append(
                exists(
                    select(CRMDelivery.id).where(
                        CRMDelivery.tenant_id == principal.tenant_id,
                        CRMDelivery.lead_id == Lead.id,
                        CRMDelivery.status == crm_status,
                    )
                )
            )
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        conditions.append(or_(Lead.name.ilike(pattern), Lead.email.ilike(pattern), Lead.phone.ilike(pattern)))
    total = int(await session.scalar(select(func.count()).select_from(Lead).where(*conditions)) or 0)
    leads = (
        await session.scalars(
            select(Lead)
            .where(*conditions)
            .order_by(Lead.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return PageResult(items=[lead_response(item) for item in leads], total=total, page=page, page_size=page_size)


@router.post("", response_model=LeadOut, status_code=201)
async def create_lead(payload: LeadCreate, principal: LeadsUpdatePrincipal, session: DB) -> LeadOut:
    agent = await session.scalar(
        select(Agent).where(
            Agent.id == payload.agent_id,
            Agent.tenant_id == principal.tenant_id,
            Agent.workspace_id == principal.workspace_id,
        )
    )
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if await get_agent_purpose(session, tenant_id=principal.tenant_id, workspace_id=principal.workspace_id, agent_id=agent.id) is AgentPurpose.EDUCATION:
        raise HTTPException(status_code=409, detail="Education agents do not create leads")
    conversation: Conversation | None = None
    if payload.conversation_id:
        conversation = await session.scalar(
            select(Conversation).where(
                Conversation.id == payload.conversation_id,
                Conversation.tenant_id == principal.tenant_id,
                Conversation.workspace_id == principal.workspace_id,
                Conversation.agent_id == payload.agent_id,
                ~education_source(Conversation),
            )
        )
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
    source_channel = conversation.channel.value if conversation is not None else "api"
    lead = Lead(
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        agent_id=payload.agent_id,
        conversation_id=payload.conversation_id,
        name=payload.name,
        email=str(payload.email) if payload.email else None,
        phone=payload.phone,
        status=LeadLifecycleStatus.NEW.value,
        consent=payload.consent,
        fields_json={**payload.fields, "sourceChannel": source_channel},
    )
    session.add(lead)
    await session.flush()
    await lead_domain_service.ensure_profile(
        session,
        lead=lead,
        source_channel=source_channel,
        source_provider=source_channel,
        source_external_id=str(conversation.visitor_id) if conversation and conversation.visitor_id else None,
    )
    event_payload = {
        "leadId": str(lead.id),
        "workspaceId": str(lead.workspace_id),
        "agentId": str(lead.agent_id),
        "conversationId": str(lead.conversation_id) if lead.conversation_id else None,
        "sourceChannel": source_channel,
    }
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="lead",
        aggregate_id=lead.id,
        event_type="lead.captured.v1",
        payload=event_payload,
    )
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="lead",
        aggregate_id=lead.id,
        event_type="lead.created.v1",
        payload=event_payload,
    )
    enqueue_crm_sync(session, lead, reason="lead_created")
    await session.commit()
    return lead_response(lead)


@router.patch("/{lead_id}", response_model=LeadOut)
async def update_lead(
    lead_id: UUID,
    payload: LeadPatch,
    principal: LeadsUpdatePrincipal,
    session: DB,
) -> LeadOut:
    if payload.status not in VALID_LEAD_STATUSES:
        raise HTTPException(status_code=400, detail="Unsupported lead status")
    lead = await session.scalar(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.tenant_id == principal.tenant_id,
            Lead.workspace_id == principal.workspace_id,
            ~education_source(Lead),
            *((Lead.agent_id.in_(principal.agent_ids),) if principal.agent_ids is not None else ()),
        ).with_for_update()
    )
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    await lead_domain_service.update_status(
        session, lead=lead, status=LeadLifecycleStatus(payload.status),
        actor_id=str(principal.user_id), correlation_id=request_id_ctx.get(),
    )
    await session.flush()
    await session.refresh(lead)
    await session.commit()
    return lead_response(lead)
