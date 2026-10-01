from __future__ import annotations

from copy import deepcopy
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.agent_purpose import AgentPurpose, get_agent_purpose, set_agent_purpose
from northstar_api.education_enrollments import EducationEnrollment, EnrollmentStatus
from northstar_api.config import get_settings
from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.lead_crm.channel_scope import AgentChannelBinding
from northstar_api.llm_providers import PROVIDER_BY_ID
from northstar_api.models import (
    Agent,
    AgentStatus,
    Conversation,
    ConversationState,
    KnowledgeSource,
    LLMConnection,
    WhatsAppConnection,
    default_appearance,
    default_security,
)
from northstar_api.schemas import (
    AgentAppearance,
    AgentCreate,
    AgentDuplicate,
    AgentModelProfile,
    AgentOut,
    AgentPatch,
    AgentSecurity,
    APIModel,
)
from northstar_api.security import Principal
from northstar_api.services.education_enrollment import (
    NON_TERMINAL_ENROLLMENT_STATUSES,
    has_active_agent_enrollment_configuration,
    has_non_terminal_enrollment,
)
from northstar_api.services.localization import localized_appearance
from northstar_api.services.outbox import enqueue_event

router = APIRouter(prefix="/agents", tags=["agents"])
DB = Annotated[AsyncSession, Depends(get_session)]
AgentsViewPrincipal = Annotated[Principal, Depends(require_permissions("agents.view"))]
AgentsCreatePrincipal = Annotated[Principal, Depends(require_permissions("agents.create"))]
AgentsUpdatePrincipal = Annotated[Principal, Depends(require_permissions("agents.update"))]
AgentsDeletePrincipal = Annotated[Principal, Depends(require_permissions("agents.delete"))]

AgentChannelType = Literal[
    "website",
    "whatsapp",
    "telegram",
    "instagram",
    "facebook",
    "slack",
    "teams",
    "api",
    "notion",
    "zapier",
]
APPEARANCE_CHANNELS = {
    "telegram",
    "website",
    "whatsapp",
    "instagram",
    "facebook",
    "slack",
    "teams",
    "api",
    "notion",
    "zapier",
}

GENERIC_SUPPORT_INSTRUCTIONS = "Help visitors with accurate, concise answers. Use trusted knowledge first and clearly say when information is unavailable."
PURPOSE_STARTER_INSTRUCTIONS: dict[AgentPurpose, str] = {
    AgentPurpose.SUPPORT: (
        "Answer customer questions using trusted knowledge. Be clear, helpful, and escalate when information is missing."
    ),
    AgentPurpose.LEAD_GENERATION: (
        "Qualify each lead with one useful question at a time, understand their needs, and recommend the appropriate next step."
    ),
    AgentPurpose.EDUCATION: (
        "Support enrolled students using only authorized course knowledge. Do not expose private course content until "
        "the platform has verified the student's active enrollment. Escalate identity or enrollment problems instead of guessing."
    ),
}


class AgentCreateWithChannel(AgentCreate):
    purpose: AgentPurpose | None = None
    whatsapp_connection_id: UUID | None = None


class AgentDuplicateWithChannel(AgentDuplicate):
    pass


class AgentPatchWithPurpose(AgentPatch):
    purpose: AgentPurpose | None = None


class AgentOutWithPurpose(AgentOut):
    purpose: AgentPurpose
    whatsapp_number: str | None = None


class AgentChannelPatch(APIModel):
    channel_type: AgentChannelType


class AgentChannelOut(APIModel):
    agent_id: UUID
    workspace_id: UUID
    channel_type: AgentChannelType


def _create_purpose(payload: AgentCreateWithChannel) -> AgentPurpose:
    if payload.purpose is not None:
        return payload.purpose
    # Preserve the old template contract for API clients that predate purpose.
    if payload.template == "lead":
        return AgentPurpose.LEAD_GENERATION
    return AgentPurpose.SUPPORT


def _starter_instructions(payload: AgentCreateWithChannel, purpose: AgentPurpose) -> str:
    # Before Agent Purpose existed, an omitted/blank template created a generic
    # support Agent while template="support" selected the specialized support
    # starter. Keep both behaviors so this schema extension is non-breaking.
    if purpose == AgentPurpose.SUPPORT and payload.template != "support":
        return GENERIC_SUPPORT_INSTRUCTIONS
    return PURPOSE_STARTER_INSTRUCTIONS[purpose]


async def _channel_binding(session: AsyncSession, agent: Agent) -> AgentChannelBinding:
    value = await session.scalar(
        select(AgentChannelBinding).where(
            AgentChannelBinding.tenant_id == agent.tenant_id,
            AgentChannelBinding.workspace_id == agent.workspace_id,
            AgentChannelBinding.agent_id == agent.id,
        )
    )
    if value is None:
        raw = str((agent.appearance or {}).get("deploymentChannel") or "website").lower()
        supported = {
            "website",
            "whatsapp",
            "telegram",
            "instagram",
            "facebook",
            "slack",
            "teams",
            "api",
            "notion",
            "zapier",
        }
        value = AgentChannelBinding(
            tenant_id=agent.tenant_id,
            workspace_id=agent.workspace_id,
            agent_id=agent.id,
            channel_type=raw if raw in supported else "website",
        )
        session.add(value)
        await session.flush()
    return value


async def agent_response(session: AsyncSession, agent: Agent) -> AgentOutWithPurpose:
    conversations = int(
        await session.scalar(
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.tenant_id == agent.tenant_id, Conversation.agent_id == agent.id)
        )
        or 0
    )
    resolved = int(
        await session.scalar(
            select(func.count())
            .select_from(Conversation)
            .where(
                Conversation.tenant_id == agent.tenant_id,
                Conversation.agent_id == agent.id,
                Conversation.state == ConversationState.RESOLVED,
            )
        )
        or 0
    )
    knowledge = int(
        await session.scalar(
            select(func.count())
            .select_from(KnowledgeSource)
            .where(KnowledgeSource.tenant_id == agent.tenant_id, KnowledgeSource.agent_id == agent.id)
        )
        or 0
    )
    purpose = await get_agent_purpose(
        session,
        tenant_id=agent.tenant_id,
        workspace_id=agent.workspace_id,
        agent_id=agent.id,
    )
    whatsapp = await session.scalar(
        select(WhatsAppConnection).where(
            WhatsAppConnection.agent_id == agent.id,
            WhatsAppConnection.tenant_id == agent.tenant_id,
            WhatsAppConnection.workspace_id == agent.workspace_id,
        )
    )
    binding = await session.scalar(
        select(AgentChannelBinding).where(
            AgentChannelBinding.tenant_id == agent.tenant_id,
            AgentChannelBinding.workspace_id == agent.workspace_id,
            AgentChannelBinding.agent_id == agent.id,
        )
    )
    appearance = dict(agent.appearance or {})
    if binding and binding.channel_type in APPEARANCE_CHANNELS:
        appearance["deploymentChannel"] = binding.channel_type
    return AgentOutWithPurpose(
        whatsapp_number=(whatsapp.display_phone_number or None) if whatsapp else None,
        id=agent.id,
        workspace_id=agent.workspace_id,
        public_id=agent.public_id,
        name=agent.name,
        description=agent.description,
        instructions=agent.instructions,
        status=agent.status,
        tone=agent.tone,
        language=agent.language,
        avatar=agent.avatar,
        purpose=purpose,
        conversations=conversations,
        resolution_rate=round((resolved / conversations) * 100, 1) if conversations else 0,
        knowledge_count=knowledge,
        last_updated=agent.updated_at,
        created_at=agent.created_at,
        appearance=AgentAppearance.model_validate(appearance),
        model=AgentModelProfile.model_validate(agent.model_profile),
        security=AgentSecurity.model_validate(agent.security),
    )


async def scoped_agent(
    session: AsyncSession,
    tenant_id: UUID,
    agent_id: UUID,
    *,
    workspace_id: UUID | None = None,
    allowed_agent_ids: frozenset[UUID] | None = None,
) -> Agent:
    conditions = [Agent.id == agent_id, Agent.tenant_id == tenant_id, Agent.deleted_at.is_(None)]
    if workspace_id:
        conditions.append(Agent.workspace_id == workspace_id)
    if allowed_agent_ids is not None:
        conditions.append(Agent.id.in_(allowed_agent_ids))
    agent = await session.scalar(select(Agent).where(*conditions))
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.get("", response_model=list[AgentOutWithPurpose])
async def list_agents(principal: AgentsViewPrincipal, session: DB) -> list[AgentOutWithPurpose]:
    conditions = [
        Agent.tenant_id == principal.tenant_id,
        Agent.workspace_id == principal.workspace_id,
        Agent.deleted_at.is_(None),
    ]
    if principal.agent_ids is not None:
        conditions.append(Agent.id.in_(principal.agent_ids))
    agents = (await session.scalars(select(Agent).where(*conditions).order_by(Agent.updated_at.desc()))).all()
    return [await agent_response(session, agent) for agent in agents]


@router.post("", response_model=AgentOutWithPurpose, status_code=201)
async def create_agent(
    payload: AgentCreateWithChannel,
    principal: AgentsCreatePrincipal,
    session: DB,
) -> AgentOutWithPurpose:
    if payload.whatsapp_connection_id is None:
        return await _create_agent(payload, principal, session)
    if payload.deployment_channel != "whatsapp":
        raise HTTPException(422, "Select WhatsApp as the deployment channel to assign a number")
    if not principal.can("integrations.manage"):
        raise HTTPException(403, "You need integration management permission to assign a WhatsApp number")
    from northstar_api.routers.whatsapp_accounts import setup_lock
    from northstar_api.modules.whatsapp.graph import token_expiry_is_current

    async with setup_lock(principal):
        connection = await session.scalar(
            select(WhatsAppConnection)
            .where(
                WhatsAppConnection.id == payload.whatsapp_connection_id,
                WhatsAppConnection.tenant_id == principal.tenant_id,
                WhatsAppConnection.workspace_id == principal.workspace_id,
            )
            .with_for_update()
        )
        if not connection:
            raise HTTPException(404, "WhatsApp number not found in this workspace")
        if connection.agent_id:
            raise HTTPException(
                409,
                "This WhatsApp number is already assigned. Choose another number or release it in Deploy.",
            )
        if connection.status != "connected" or not token_expiry_is_current(connection.token_expires_at):
            raise HTTPException(
                409, "Activate the number's webhook and reconnect any expired token before selecting it"
            )
        return await _create_agent(payload, principal, session, connection)


async def _create_agent(payload, principal, session, connection=None) -> AgentOutWithPurpose:
    purpose = _create_purpose(payload)
    appearance = default_appearance()
    appearance.update(localized_appearance(payload.language))
    # Keep the appearance channel in sync with the deployment binding.
    appearance["deploymentChannel"] = (
        payload.deployment_channel if payload.deployment_channel in APPEARANCE_CHANNELS else "website"
    )
    instructions = _starter_instructions(payload, purpose)
    security = default_security()
    # Grounded knowledge is the safe default. Web evidence remains an explicit
    # owner choice instead of silently widening a newly created bot's scope.
    security["webFallback"] = "off"
    # Education Agents cannot be made live before the enrollment authorization
    # layer exists. Creating them in draft prevents private knowledge from being
    # exposed through the existing generic runtime while Education is provisioned.
    initial_status = (
        AgentStatus.DRAFT
        if purpose == AgentPurpose.EDUCATION or payload.deployment_channel == "whatsapp"
        else AgentStatus.ACTIVE
    )
    agent = Agent(
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        name=payload.name.strip(),
        description=payload.description.strip(),
        instructions=instructions,
        status=initial_status,
        tone=payload.tone,
        language=payload.language,
        appearance=appearance,
        security=security,
    )
    session.add(agent)
    try:
        await session.flush()
        if connection is not None:
            connection.agent_id = agent.id
        await set_agent_purpose(session, agent=agent, purpose=purpose)
        session.add(
            AgentChannelBinding(
                tenant_id=principal.tenant_id,
                workspace_id=principal.workspace_id,
                agent_id=agent.id,
                channel_type=payload.deployment_channel,
            )
        )
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="An agent with this name already exists") from None
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="agent",
        aggregate_id=agent.id,
        event_type="agent.created.v1",
        payload={
            "agentId": str(agent.id),
            "workspaceId": str(principal.workspace_id),
            "channelType": payload.deployment_channel,
            "purpose": purpose.value,
        },
    )
    await session.commit()
    return await agent_response(session, agent)


@router.get("/{agent_id}", response_model=AgentOutWithPurpose)
async def get_agent(agent_id: UUID, principal: AgentsViewPrincipal, session: DB) -> AgentOutWithPurpose:
    return await agent_response(
        session,
        await scoped_agent(
            session,
            principal.tenant_id,
            agent_id,
            workspace_id=principal.workspace_id,
            allowed_agent_ids=principal.agent_ids,
        ),
    )


@router.get("/{agent_id}/channel", response_model=AgentChannelOut)
async def get_agent_channel(
    agent_id: UUID,
    principal: AgentsViewPrincipal,
    session: DB,
) -> AgentChannelOut:
    agent = await scoped_agent(
        session,
        principal.tenant_id,
        agent_id,
        workspace_id=principal.workspace_id,
        allowed_agent_ids=principal.agent_ids,
    )
    binding = await _channel_binding(session, agent)
    await session.commit()
    return AgentChannelOut(
        agent_id=agent.id,
        workspace_id=agent.workspace_id,
        channel_type=binding.channel_type,
    )


@router.patch("/{agent_id}/channel", response_model=AgentChannelOut)
async def update_agent_channel(
    agent_id: UUID,
    payload: AgentChannelPatch,
    principal: AgentsUpdatePrincipal,
    session: DB,
) -> AgentChannelOut:
    agent = await scoped_agent(
        session,
        principal.tenant_id,
        agent_id,
        workspace_id=principal.workspace_id,
        allowed_agent_ids=principal.agent_ids,
    )
    binding = await _channel_binding(session, agent)
    binding.channel_type = payload.channel_type
    if payload.channel_type in APPEARANCE_CHANNELS:
        appearance = deepcopy(agent.appearance)
        appearance["deploymentChannel"] = payload.channel_type
        agent.appearance = appearance
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="agent",
        aggregate_id=agent.id,
        event_type="agent.channel.changed.v1",
        payload={
            "agentId": str(agent.id),
            "workspaceId": str(agent.workspace_id),
            "channelType": payload.channel_type,
        },
    )
    await session.commit()
    return AgentChannelOut(
        agent_id=agent.id,
        workspace_id=agent.workspace_id,
        channel_type=binding.channel_type,
    )


@router.post("/{agent_id}/duplicate", response_model=AgentOutWithPurpose, status_code=201)
async def duplicate_agent(
    agent_id: UUID,
    payload: AgentDuplicateWithChannel,
    principal: AgentsCreatePrincipal,
    session: DB,
) -> AgentOutWithPurpose:
    source = await scoped_agent(
        session, principal.tenant_id, agent_id,
        workspace_id=principal.workspace_id, allowed_agent_ids=principal.agent_ids,
    )
    source_purpose = await get_agent_purpose(
        session,
        tenant_id=source.tenant_id,
        workspace_id=source.workspace_id,
        agent_id=source.id,
    )
    appearance = deepcopy(source.appearance)
    if payload.deployment_channel in APPEARANCE_CHANNELS:
        appearance["deploymentChannel"] = payload.deployment_channel
    duplicate = Agent(
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        name=payload.name.strip(),
        description=source.description,
        instructions=source.instructions,
        status=AgentStatus.DRAFT,
        tone=source.tone,
        language=source.language,
        avatar=source.avatar,
        appearance=appearance,
        model_profile=deepcopy(source.model_profile),
        security=deepcopy(source.security),
    )
    session.add(duplicate)
    try:
        await session.flush()
        await set_agent_purpose(session, agent=duplicate, purpose=source_purpose)
        session.add(
            AgentChannelBinding(
                tenant_id=principal.tenant_id,
                workspace_id=principal.workspace_id,
                agent_id=duplicate.id,
                channel_type=payload.deployment_channel,
            )
        )
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="An agent with this name already exists") from None
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="agent",
        aggregate_id=duplicate.id,
        event_type="agent.duplicated.v1",
        payload={
            "agentId": str(duplicate.id),
            "sourceAgentId": str(source.id),
            "workspaceId": str(principal.workspace_id),
            "deploymentChannel": payload.deployment_channel,
            "purpose": source_purpose.value,
        },
    )
    await session.commit()
    await session.refresh(duplicate)
    return await agent_response(session, duplicate)


@router.patch("/{agent_id}", response_model=AgentOutWithPurpose)
async def update_agent(
    agent_id: UUID,
    payload: AgentPatchWithPurpose,
    principal: AgentsUpdatePrincipal,
    session: DB,
) -> AgentOutWithPurpose:
    agent = await scoped_agent(
        session, principal.tenant_id, agent_id,
        workspace_id=principal.workspace_id, allowed_agent_ids=principal.agent_ids,
    )
    current_purpose = await get_agent_purpose(
        session,
        tenant_id=agent.tenant_id,
        workspace_id=agent.workspace_id,
        agent_id=agent.id,
    )
    requested_purpose = payload.purpose or current_purpose
    current_channel = (agent.appearance or {}).get("deploymentChannel")
    requested_channel = payload.appearance.deployment_channel if payload.appearance else current_channel
    activating = payload.status == AgentStatus.ACTIVE or (
        payload.status is None and agent.status == AgentStatus.ACTIVE and requested_channel != current_channel
    )
    if activating and requested_channel == "whatsapp":
        from northstar_api.modules.whatsapp.graph import token_expiry_is_current

        connection = await session.scalar(select(WhatsAppConnection).where(
            WhatsAppConnection.tenant_id == agent.tenant_id,
            WhatsAppConnection.workspace_id == agent.workspace_id,
            WhatsAppConnection.agent_id == agent.id,
        ))
        if not connection or connection.status != "connected" or not token_expiry_is_current(connection.token_expires_at):
            raise HTTPException(409, "Connect a WhatsApp number and activate its webhook in Integrations before activating this bot.")
    if payload.status == AgentStatus.ACTIVE and requested_purpose == AgentPurpose.EDUCATION:
        configured = await has_active_agent_enrollment_configuration(
            session,
            tenant_id=agent.tenant_id,
            workspace_id=agent.workspace_id,
            agent_id=agent.id,
        )
        if not configured:
            raise HTTPException(
                status_code=409,
                detail="Create and activate at least one valid Student Enrollment before activating this Education Agent.",
            )

    patch = payload.model_dump(exclude_unset=True)
    if "purpose" in patch:
        assert payload.purpose is not None
        if (
            payload.purpose != current_purpose
            and current_purpose == AgentPurpose.EDUCATION
            and await has_non_terminal_enrollment(
                session,
                tenant_id=agent.tenant_id,
                workspace_id=agent.workspace_id,
                agent_id=agent.id,
            )
        ):
            raise HTTPException(
                status_code=409,
                detail="Resolve non-terminal Education Enrollments before changing this Agent purpose.",
            )
        await set_agent_purpose(session, agent=agent, purpose=payload.purpose)
        patch.pop("purpose")
        if payload.purpose != current_purpose and payload.purpose == AgentPurpose.EDUCATION and agent.status == AgentStatus.ACTIVE:
            agent.status = AgentStatus.DRAFT
        if payload.purpose != current_purpose:
            enqueue_event(
                session,
                tenant_id=principal.tenant_id,
                aggregate_type="agent",
                aggregate_id=agent.id,
                event_type="agent.purpose.changed.v1",
                payload={
                    "agentId": str(agent.id),
                    "workspaceId": str(agent.workspace_id),
                    "previousPurpose": current_purpose.value,
                    "purpose": payload.purpose.value,
                    "status": agent.status.value,
                },
            )
    if "model" in patch:
        assert payload.model is not None
        if payload.model.provider not in PROVIDER_BY_ID:
            raise HTTPException(status_code=422, detail="Unsupported model provider")
        if payload.model.provider != "nvidia" and payload.model.connection_id is None:
            raise HTTPException(status_code=422, detail="Select a saved provider connection for this model")
        if payload.model.connection_id is not None:
            connection = await session.scalar(
                select(LLMConnection).where(
                    LLMConnection.id == payload.model.connection_id,
                    LLMConnection.tenant_id == agent.tenant_id,
                    LLMConnection.workspace_id == agent.workspace_id,
                )
            )
            if connection is None:
                raise HTTPException(status_code=422, detail="Selected provider connection was not found")
            if connection.provider != payload.model.provider:
                raise HTTPException(status_code=422, detail="Provider connection does not match the selected model")
        agent.model_profile = payload.model.model_dump(by_alias=True)
        # Keep one authoritative, visible internet policy. The model dropdown
        # maps to the existing bounded web retrieval policy; models never get
        # arbitrary server-side network access.
        internet_policy = {
            "none": "off",
            "allowlisted": "related_only",
            "public": "public",
        }[payload.model.internet_access]
        security = deepcopy(agent.security)
        security["webFallback"] = internet_policy
        agent.security = security
        patch.pop("model")
    if "appearance" in patch:
        assert payload.appearance is not None
        agent.appearance = payload.appearance.model_dump(by_alias=True)
        binding = await _channel_binding(session, agent)
        binding.channel_type = payload.appearance.deployment_channel
        patch.pop("appearance")
    if "security" in patch:
        assert payload.security is not None
        agent.security = payload.security.model_dump(by_alias=True)
        patch.pop("security")
        # A full agent save includes both objects. The model dropdown is the
        # canonical internet policy, so do not let a stale security snapshot
        # overwrite the newly selected provider access level.
        if "model" in payload.model_fields_set and payload.model is not None:
            security = deepcopy(agent.security)
            security["webFallback"] = {
                "none": "off",
                "allowlisted": "related_only",
                "public": "public",
            }[payload.model.internet_access]
            agent.security = security
    if "language" in patch and "appearance" not in payload.model_fields_set:
        next_appearance = deepcopy(agent.appearance)
        next_appearance.update(localized_appearance(str(patch["language"])))
        agent.appearance = next_appearance
    for name, value in patch.items():
        setattr(agent, name, value)
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="agent",
        aggregate_id=agent.id,
        event_type="agent.updated.v1",
        payload={
            "agentId": str(agent.id),
            "workspaceId": str(agent.workspace_id),
            "purpose": requested_purpose.value,
            "fields": sorted(payload.model_fields_set),
        },
    )
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="An agent with this name already exists") from None
    await session.refresh(agent)
    return await agent_response(session, agent)


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(agent_id: UUID, principal: AgentsDeletePrincipal, session: DB) -> Response:
    from datetime import UTC, datetime

    agent = await scoped_agent(
        session, principal.tenant_id, agent_id,
        workspace_id=principal.workspace_id, allowed_agent_ids=principal.agent_ids,
    )
    await session.execute(
        update(EducationEnrollment).where(
            EducationEnrollment.tenant_id == agent.tenant_id,
            EducationEnrollment.workspace_id == agent.workspace_id,
            EducationEnrollment.agent_id == agent.id,
            EducationEnrollment.status.in_(NON_TERMINAL_ENROLLMENT_STATUSES),
        ).values(status=EnrollmentStatus.REVOKED.value)
    )
    agent.status = AgentStatus.DRAFT
    agent.deleted_at = datetime.now(UTC)
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="agent",
        aggregate_id=agent.id,
        event_type="agent.deleted.v1",
        payload={"agentId": str(agent.id), "workspaceId": str(agent.workspace_id)},
    )
    await session.commit()
    return Response(status_code=204)
