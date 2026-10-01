"""Transactional, explicitly requested starter copies; no deployment or provider calls."""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from northstar_api.access_policy import effective_permissions
from northstar_api.agent_purpose import AgentPurpose, AgentPurposeSetting
from northstar_api.lead_crm.audit import record_audit_event
from northstar_api.lead_crm.channel_scope import AgentChannelBinding
from northstar_api.models import (
    Agent, AgentStatus, AgentTone, TenantMembership, User, Workspace,
    WorkspaceMemberAgentAccess, WorkspaceMembership, WorkspaceStatus, default_appearance,
)
from northstar_api.onboarding_models import OrganizationSetup
from northstar_api.security import Principal
from northstar_api.services.entitlements import _serialize_capacity_check, require_capacity, require_channel
from northstar_api.services.localization import localized_appearance
from northstar_api.services.outbox import enqueue_event
from northstar_api.starter_content_contract import (
    TEMPLATE_IDS, StarterTemplate, TemplateCloneOut, TemplateCloneRequest,
    approved_template, clone_fingerprint,
)
from northstar_api.starter_content_models import StarterTemplateClone

REQUIRED_PERMISSIONS = frozenset({"starter_content.read", "agents.create", "agents.view"})


class StarterContentError(ValueError):
    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class CloneContext:
    workspace: Workspace
    membership: WorkspaceMembership
    grants: list[str]


def _require_interactive(principal: Principal) -> None:
    if principal.workspace_id is None or principal.token_id.startswith("api_key:"):
        raise StarterContentError("Select a workspace in an interactive session", 403)
    if not all(principal.can(permission) for permission in REQUIRED_PERMISSIONS):
        raise StarterContentError("Starter content, agent creation and agent view permissions are required", 403)


def _context(session: Session, principal: Principal, *, lock: bool = False) -> CloneContext:
    """Recheck stored membership and profile; never trust the request's cached grants alone."""
    _require_interactive(principal)
    workspace_query = select(Workspace).where(
        Workspace.id == principal.workspace_id, Workspace.tenant_id == principal.tenant_id,
        Workspace.status == WorkspaceStatus.ACTIVE,
    )
    workspace = session.scalar(workspace_query.with_for_update() if lock else workspace_query)
    member_query = select(WorkspaceMembership).where(
        WorkspaceMembership.workspace_id == principal.workspace_id,
        WorkspaceMembership.tenant_id == principal.tenant_id,
        WorkspaceMembership.user_id == principal.user_id,
    )
    membership = session.scalar(member_query.with_for_update() if lock else member_query)
    organization_query = select(TenantMembership).join(User, User.id == TenantMembership.user_id).where(
        TenantMembership.tenant_id == principal.tenant_id,
        TenantMembership.user_id == principal.user_id, User.is_active.is_(True),
    )
    organization = session.scalar(organization_query.with_for_update() if lock else organization_query)
    if workspace is None or membership is None or organization is None:
        raise StarterContentError("Workspace access is unavailable", 403)
    if organization.role != principal.role or not REQUIRED_PERMISSIONS <= effective_permissions(
        organization.role.value, membership.role.value,
    ):
        raise StarterContentError("Your access changed. Reload the workspace", 403)
    setup_query = select(OrganizationSetup).where(OrganizationSetup.tenant_id == principal.tenant_id)
    setup = session.scalar(setup_query.with_for_update() if lock else setup_query)
    if setup is None or (setup.required and not setup.profile_complete):
        raise StarterContentError("Complete organization setup before copying starter material", 428)
    return CloneContext(workspace, membership, list(setup.catalog_grants))


def _receipt(session: Session, principal: Principal, request_id: UUID) -> StarterTemplateClone | None:
    return session.scalar(select(StarterTemplateClone).where(
        StarterTemplateClone.tenant_id == principal.tenant_id,
        StarterTemplateClone.workspace_id == principal.workspace_id,
        StarterTemplateClone.actor_id == principal.user_id,
        StarterTemplateClone.request_id == request_id,
    ))


def _response(session: Session, principal: Principal, context: CloneContext,
              receipt: StarterTemplateClone, *, replayed: bool) -> TemplateCloneOut:
    if receipt.catalog_id not in context.grants or receipt.catalog_id not in TEMPLATE_IDS:
        raise StarterContentError("This starter template is no longer available", 403)
    if receipt.agent_id is None:
        raise StarterContentError("The copied agent was deleted; this request cannot recreate it", 410)
    agent = session.scalar(select(Agent).where(
        Agent.id == receipt.agent_id, Agent.tenant_id == principal.tenant_id,
        Agent.workspace_id == principal.workspace_id, Agent.deleted_at.is_(None),
    ))
    if agent is None:
        raise StarterContentError("The copied agent is no longer available; it has not been recreated", 410)
    if not context.membership.all_agents_access:
        grant = session.scalar(select(WorkspaceMemberAgentAccess.agent_id).where(
            WorkspaceMemberAgentAccess.workspace_id == principal.workspace_id,
            WorkspaceMemberAgentAccess.user_id == principal.user_id,
            WorkspaceMemberAgentAccess.agent_id == agent.id,
        ))
        if grant is None:
            raise StarterContentError("Access to the copied agent was removed", 403)
    return TemplateCloneOut(
        request_id=receipt.request_id, catalog_id=receipt.catalog_id,
        catalog_version=receipt.catalog_version, agent_id=agent.id,
        workspace_id=agent.workspace_id, name=receipt.name,
        created_at=receipt.created_at, replayed=replayed,
    )


def _make_copy(session: Session, principal: Principal, context: CloneContext,
               template: StarterTemplate, payload: TemplateCloneRequest) -> StarterTemplateClone:
    appearance = default_appearance()
    appearance.update(localized_appearance(context.workspace.default_language))
    appearance["deploymentChannel"] = "website"
    agent = Agent(
        id=uuid4(), tenant_id=principal.tenant_id, workspace_id=context.workspace.id,
        name=payload.name, description=f"Starter copy: {template.title} (version {template.version}). Review before deployment.",
        instructions=template.instructions, status=AgentStatus.DRAFT, tone=AgentTone.FRIENDLY,
        language=context.workspace.default_language, appearance=appearance,
    )
    # Agent defaults retain the configured NVIDIA model and normal security policy.
    # No knowledge, student, conversation, lead, channel credential or key is copied.
    session.add(agent)
    session.flush()
    session.add(AgentPurposeSetting(agent_id=agent.id, tenant_id=principal.tenant_id,
                                   workspace_id=context.workspace.id, purpose=AgentPurpose.SUPPORT.value))
    session.add(AgentChannelBinding(agent_id=agent.id, tenant_id=principal.tenant_id,
                                   workspace_id=context.workspace.id, channel_type="website"))
    if not context.membership.all_agents_access:
        session.add(WorkspaceMemberAgentAccess(workspace_id=context.workspace.id,
                                               user_id=principal.user_id, agent_id=agent.id))
    receipt = StarterTemplateClone(
        id=uuid4(), tenant_id=principal.tenant_id, workspace_id=context.workspace.id,
        actor_id=principal.user_id, request_id=payload.idempotency_key,
        catalog_id=template.id, catalog_version=template.version, recipe_digest=template.digest,
        fingerprint=clone_fingerprint(template, payload), agent_id=agent.id, name=payload.name,
    )
    session.add(receipt)
    session.flush()
    return receipt


async def clone_template(session: AsyncSession, principal: Principal, catalog_id: str,
                         payload: TemplateCloneRequest) -> TemplateCloneOut:
    _require_interactive(principal)
    # Use the SAME tenant/resource transaction lock as existing agent creation.
    # No commit may occur between this lock, the quota check and the receipt.
    await _serialize_capacity_check(session, tenant_id=principal.tenant_id, resource="agents")
    context = await session.run_sync(_context, principal, lock=True)
    receipt = await session.run_sync(_receipt, principal, payload.idempotency_key)
    if receipt is not None:
        if (receipt.catalog_id, receipt.catalog_version, receipt.name) != (
            catalog_id, payload.catalog_version, payload.name,
        ):
            raise StarterContentError("This request ID was already used with different clone settings")
        # A retry returns its original copy even when the plan is now full. It
        # consumes no new quota and never restores removed access or deleted data.
        return await session.run_sync(_response, principal, context, receipt, replayed=True)
    try:
        template = approved_template(catalog_id, payload.catalog_version, context.grants)
    except LookupError as exc:
        raise StarterContentError(str(exc), 404) from None
    except ValueError as exc:
        raise StarterContentError(str(exc)) from None
    await require_channel(session, tenant_id=principal.tenant_id, provider="widget")
    await require_capacity(session, tenant_id=principal.tenant_id, resource="agents")
    receipt = await session.run_sync(_make_copy, principal, context, template, payload)
    assert receipt.agent_id is not None
    metadata = {"catalogId": template.id, "catalogVersion": template.version,
                "agentId": str(receipt.agent_id), "requestId": str(payload.idempotency_key),
                "recipeDigest": template.digest, "sample": True, "initialStatus": "draft"}
    record_audit_event(session, tenant_id=principal.tenant_id, workspace_id=context.workspace.id,
                       actor_user_id=principal.user_id, action="starter_content.cloned",
                       entity_type="agent", entity_id=str(receipt.agent_id), category="agent", metadata=metadata)
    enqueue_event(session, tenant_id=principal.tenant_id, aggregate_type="agent", aggregate_id=receipt.agent_id,
                  event_type="agent.created.v1", payload={**metadata, "workspaceId": str(context.workspace.id),
                                                          "channelType": "website", "purpose": "support"})
    enqueue_event(session, tenant_id=principal.tenant_id, aggregate_type="starter_clone", aggregate_id=receipt.id,
                  event_type="starter_content.cloned.v1", payload={**metadata, "workspaceId": str(context.workspace.id)})
    await session.flush()
    return await session.run_sync(_response, principal, context, receipt, replayed=False)


async def clone_result(session: AsyncSession, principal: Principal, request_id: UUID) -> TemplateCloneOut:
    context = await session.run_sync(_context, principal)
    receipt = await session.run_sync(_receipt, principal, request_id)
    if receipt is None:
        raise StarterContentError("No completed copy was found for this request in the selected workspace", 404)
    return await session.run_sync(_response, principal, context, receipt, replayed=True)
