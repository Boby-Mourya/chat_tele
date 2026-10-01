from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.agent_purpose import AgentPurpose, AgentPurposeSetting
from northstar_api.lead_crm.crm_workflow_schemas import (
    CRMWorkflowConnectionOut,
    CRMWorkflowCountsOut,
    CRMWorkflowDeliveryOut,
    CRMWorkflowJourneyOut,
    CRMWorkflowJourneyStage,
    CRMWorkflowOut,
    CRMWorkflowReadinessOut,
    CRMWorkflowReadinessStageOut,
    CRMWorkflowStageStatus,
)
from northstar_api.lead_crm.domain import CRMDeliveryStatus
from northstar_api.lead_crm.models import (
    CRMConnection,
    CRMDelivery,
    CRMFieldMapping,
    CRMRoute,
    IntegrationDeadLetter,
    LeadProfile,
)
from northstar_api.lead_crm.workspace_scope import WorkspaceCRMConnection, WorkspaceCRMRoute
from northstar_api.models import Agent, AgentStatus, Conversation, ConversationState, Lead

_IN_FLIGHT_STATUSES = {
    CRMDeliveryStatus.CREATED.value,
    CRMDeliveryStatus.ROUTED.value,
    CRMDeliveryStatus.QUEUED.value,
    CRMDeliveryStatus.PROCESSING.value,
    CRMDeliveryStatus.SENT.value,
    CRMDeliveryStatus.ACKNOWLEDGED.value,
    CRMDeliveryStatus.VERIFYING.value,
    CRMDeliveryStatus.RETRYING.value,
    CRMDeliveryStatus.RATE_LIMITED.value,
}
_ATTENTION_STATUSES = {
    CRMDeliveryStatus.AUTH_REQUIRED.value,
    CRMDeliveryStatus.MAPPING_ERROR.value,
    CRMDeliveryStatus.FAILED.value,
    CRMDeliveryStatus.DEAD_LETTER.value,
}
_USABLE_CONNECTION_STATUSES = {"healthy", "degraded"}
_BLOCKED_CONNECTION_STATUSES = {
    "unhealthy",
    "auth_required",
    "configuration_error",
    "disabled",
}


def _connection_ids_from_route(route: CRMRoute) -> tuple[UUID, ...]:
    values: list[UUID] = []
    for raw in (route.actions_json or {}).get("connectionIds", []):
        try:
            value = UUID(str(raw))
        except (TypeError, ValueError):
            continue
        if value not in values:
            values.append(value)
    return tuple(values)


def _readiness_stage(
    *,
    stage_id: str,
    label: str,
    description: str,
    ready: bool,
    warning: bool,
    ready_detail: str,
    warning_detail: str,
    blocked_detail: str,
    action_label: str | None = None,
    action_path: str | None = None,
) -> CRMWorkflowReadinessStageOut:
    status: CRMWorkflowStageStatus
    if ready:
        status = "ready"
        detail = ready_detail
    elif warning:
        status = "warning"
        detail = warning_detail
    else:
        status = "blocked"
        detail = blocked_detail
    return CRMWorkflowReadinessStageOut(
        id=stage_id,
        label=label,
        description=description,
        status=status,
        detail=detail,
        action_label=None if ready else action_label,
        action_path=None if ready else action_path,
    )


def _journey_state(
    delivery: CRMDelivery | None,
    *,
    has_connections: bool,
    has_mapping: bool,
    has_route: bool,
    auto_sync_enabled: bool,
    dead_letter_open: bool,
) -> tuple[CRMWorkflowJourneyStage, str, str, str | None, str | None]:
    if delivery is None:
        if not has_connections:
            return (
                "local_lead",
                "Local lead only",
                "The Lead is stored locally, but this workspace has no CRM connection.",
                "Connect CRM",
                "/integrations",
            )
        if not has_mapping:
            return (
                "local_lead",
                "Mapping required",
                "The Lead is stored locally. Configure the Leads field mapping before delivery.",
                "Configure mapping",
                "/integrations",
            )
        if not has_route:
            return (
                "awaiting_routing",
                "Routing required",
                "No enabled workspace route currently selects a CRM connection for this Lead.",
                "Configure routing",
                "/integrations",
            )
        if not auto_sync_enabled:
            return (
                "local_lead",
                "Manual sync required",
                "Automatic new-Lead synchronization is disabled for the configured connection.",
                "Open Lead",
                "/leads",
            )
        return (
            "awaiting_routing",
            "Awaiting CRM routing",
            "The Lead is ready for the asynchronous CRM router and delivery workers.",
            "Open Lead",
            "/leads",
        )

    status = delivery.status
    if dead_letter_open or status == CRMDeliveryStatus.DEAD_LETTER.value:
        return (
            "dead_letter",
            "Dead letter",
            "Delivery exhausted its retry policy and requires an operator replay or cancellation decision.",
            "Open recovery",
            "/integrations",
        )
    if status == CRMDeliveryStatus.VERIFIED.value:
        return (
            "verified",
            "Verified in CRM",
            "The provider record ID was acknowledged and read-back verification completed.",
            "Open Lead",
            "/leads",
        )
    if status == CRMDeliveryStatus.VERIFYING.value:
        return (
            "verifying",
            "Read-back verification",
            "The provider accepted the write. The platform is checking the external record without resending it.",
            "Open Lead",
            "/leads",
        )
    if status == CRMDeliveryStatus.ACKNOWLEDGED.value:
        return (
            "provider_acknowledged",
            "Provider acknowledged",
            "The write has an external record ID and is waiting for the read-back verification cycle.",
            "Open Lead",
            "/leads",
        )
    if status in _ATTENTION_STATUSES:
        action = "Reconnect CRM" if status == CRMDeliveryStatus.AUTH_REQUIRED.value else "Review recovery"
        path = (
            "/integrations"
            if status
            in {
                CRMDeliveryStatus.AUTH_REQUIRED.value,
                CRMDeliveryStatus.MAPPING_ERROR.value,
            }
            else "/leads"
        )
        return (
            "attention_required",
            "Attention required",
            "The delivery is blocked and exposes a classified error for deterministic recovery.",
            action,
            path,
        )
    if status in _IN_FLIGHT_STATUSES:
        return (
            "in_progress",
            "CRM delivery in progress",
            "The durable delivery is queued, processing, retrying, or waiting for provider capacity.",
            "Open Lead",
            "/leads",
        )
    return (
        "attention_required",
        "Review delivery",
        "The delivery is not in a terminal verified state and should be reviewed.",
        "Open Lead",
        "/leads",
    )


class CRMWorkflowService:
    async def build(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        workspace_id: UUID,
        allowed_agent_ids: frozenset[UUID] | None,
        limit: int,
    ) -> CRMWorkflowOut:
        agent_conditions = [
            Agent.tenant_id == tenant_id,
            Agent.workspace_id == workspace_id,
            Agent.status == AgentStatus.ACTIVE,
            AgentPurposeSetting.purpose == AgentPurpose.LEAD_GENERATION.value,
        ]
        if allowed_agent_ids is not None:
            agent_conditions.append(Agent.id.in_(allowed_agent_ids))
        lead_agent_count = int(
            await session.scalar(
                select(func.count())
                .select_from(Agent)
                .join(
                    AgentPurposeSetting,
                    AgentPurposeSetting.agent_id == Agent.id,
                )
                .where(*agent_conditions)
            )
            or 0
        )

        connection_rows = (
            await session.execute(
                select(CRMConnection, WorkspaceCRMConnection)
                .join(
                    WorkspaceCRMConnection,
                    WorkspaceCRMConnection.connection_id == CRMConnection.id,
                )
                .where(
                    CRMConnection.tenant_id == tenant_id,
                    WorkspaceCRMConnection.tenant_id == tenant_id,
                    WorkspaceCRMConnection.workspace_id == workspace_id,
                )
                .order_by(CRMConnection.created_at)
            )
        ).all()
        connection_ids = [connection.id for connection, _ in connection_rows]

        mappings = (
            list(
                await session.scalars(
                    select(CRMFieldMapping).where(
                        CRMFieldMapping.tenant_id == tenant_id,
                        CRMFieldMapping.connection_id.in_(connection_ids),
                        CRMFieldMapping.object_name == "Leads",
                    )
                )
            )
            if connection_ids
            else []
        )
        mapping_by_connection = {mapping.connection_id: mapping for mapping in mappings}

        routes = list(
            await session.scalars(
                select(CRMRoute)
                .join(WorkspaceCRMRoute, WorkspaceCRMRoute.route_id == CRMRoute.id)
                .where(
                    CRMRoute.tenant_id == tenant_id,
                    CRMRoute.enabled.is_(True),
                    WorkspaceCRMRoute.tenant_id == tenant_id,
                    WorkspaceCRMRoute.workspace_id == workspace_id,
                )
                .order_by(CRMRoute.priority, CRMRoute.created_at)
            )
        )
        route_count_by_connection: dict[UUID, int] = defaultdict(int)
        for route in routes:
            for connection_id in _connection_ids_from_route(route):
                if connection_id in connection_ids:
                    route_count_by_connection[connection_id] += 1

        connections: list[CRMWorkflowConnectionOut] = []
        for connection, scope in connection_rows:
            mapping = mapping_by_connection.get(connection.id)
            mapping_configured = bool(mapping and mapping.mapping_json)
            enabled_route_count = route_count_by_connection.get(connection.id, 0)
            credentials_configured = bool(connection.credentials_encrypted or connection.credentials_ref)
            ready = (
                connection.status == "healthy"
                and credentials_configured
                and mapping_configured
                and enabled_route_count > 0
                and scope.auto_sync_new_leads
            )
            connections.append(
                CRMWorkflowConnectionOut(
                    id=connection.id,
                    name=connection.name,
                    provider=connection.provider,
                    environment=connection.environment,
                    status=connection.status,
                    credentials_configured=credentials_configured,
                    mapping_configured=mapping_configured,
                    mapping_status=mapping.status if mapping else None,
                    mapping_version=mapping.version if mapping else None,
                    enabled_route_count=enabled_route_count,
                    auto_sync_new_leads=scope.auto_sync_new_leads,
                    auto_sync_updates=scope.auto_sync_updates,
                    ready=ready,
                    last_health_at=connection.last_health_at,
                    last_success_at=connection.last_success_at,
                    last_failure_at=connection.last_failure_at,
                    last_error=connection.last_error,
                )
            )

        has_connections = bool(connections)
        has_usable_connection = any(
            connection.status in _USABLE_CONNECTION_STATUSES for connection in connections
        )
        has_blocked_connection = any(
            connection.status in _BLOCKED_CONNECTION_STATUSES for connection in connections
        )
        has_mapping = any(connection.mapping_configured for connection in connections)
        has_route = any(connection.enabled_route_count > 0 for connection in connections)
        auto_sync_enabled = any(connection.auto_sync_new_leads for connection in connections)
        healthy_connection = any(connection.status == "healthy" for connection in connections)
        degraded_connection = any(connection.status == "degraded" for connection in connections)

        readiness_stages = [
            _readiness_stage(
                stage_id="lead_generation",
                label="Lead generation Agent",
                description=(
                    "At least one active Agent must use the lead_generation purpose so resolving "
                    "a conversation creates the idempotent local Lead."
                ),
                ready=lead_agent_count > 0,
                warning=False,
                ready_detail=f"{lead_agent_count} active Lead Generation Agent(s) are available.",
                warning_detail="",
                blocked_detail="No active Lead Generation Agent exists in this workspace.",
                action_label="Create Lead Agent",
                action_path="/agents",
            ),
            _readiness_stage(
                stage_id="crm_connection",
                label="Workspace CRM connection",
                description=("Credentials and provider configuration are scoped to the active workspace."),
                ready=has_usable_connection,
                warning=has_connections,
                ready_detail="A workspace CRM connection is available for delivery.",
                warning_detail=(
                    "A CRM connection exists, but it is not currently healthy. Test or reconnect it."
                ),
                blocked_detail="No CRM connection is assigned to this workspace.",
                action_label="Open CRM setup",
                action_path="/integrations",
            ),
            _readiness_stage(
                stage_id="field_mapping",
                label="Lead field mapping",
                description=("Canonical Lead fields are transformed into the provider's Leads object."),
                ready=has_mapping,
                warning=False,
                ready_detail="A Leads mapping is configured.",
                warning_detail="",
                blocked_detail="No Leads field mapping is configured.",
                action_label="Configure mapping",
                action_path="/integrations",
            ),
            _readiness_stage(
                stage_id="routing",
                label="Workspace routing",
                description=("An enabled route must select an assigned CRM connection for matching Leads."),
                ready=has_route,
                warning=False,
                ready_detail="At least one enabled workspace route targets a CRM connection.",
                warning_detail="",
                blocked_detail="No enabled CRM route targets a connection in this workspace.",
                action_label="Configure routing",
                action_path="/integrations",
            ),
            _readiness_stage(
                stage_id="auto_sync",
                label="Automatic new-Lead sync",
                description=("New Leads can enter the durable CRM router automatically after resolution."),
                ready=auto_sync_enabled,
                warning=has_connections,
                ready_detail="Automatic synchronization is enabled for new Leads.",
                warning_detail=("CRM is configured, but automatic new-Lead synchronization is disabled."),
                blocked_detail="Automatic synchronization cannot run without a CRM connection.",
                action_label="Open CRM settings",
                action_path="/integrations",
            ),
            _readiness_stage(
                stage_id="provider_health",
                label="Provider health",
                description=(
                    "A healthy connection confirms credentials and provider reachability before "
                    "automatic delivery."
                ),
                ready=healthy_connection,
                warning=degraded_connection or (has_connections and not has_blocked_connection),
                ready_detail="At least one CRM connection is healthy.",
                warning_detail=(
                    "No connection is fully healthy; the workflow can be inspected but requires "
                    "a successful health check."
                ),
                blocked_detail=(
                    "All CRM connections are blocked by authentication, configuration, or health errors."
                    if has_connections
                    else "Provider health is unavailable until a CRM connection is created."
                ),
                action_label="Test connection",
                action_path="/integrations",
            ),
        ]
        workflow_ready = lead_agent_count > 0 and any(connection.ready for connection in connections)

        lead_conditions = [
            Lead.tenant_id == tenant_id,
            Lead.workspace_id == workspace_id,
        ]
        conversation_conditions = [
            Conversation.tenant_id == tenant_id,
            Conversation.workspace_id == workspace_id,
            Conversation.state == ConversationState.RESOLVED,
        ]
        if allowed_agent_ids is not None:
            lead_conditions.append(Lead.agent_id.in_(allowed_agent_ids))
            conversation_conditions.append(Conversation.agent_id.in_(allowed_agent_ids))

        resolved_conversations = int(
            await session.scalar(
                select(func.count()).select_from(Conversation).where(*conversation_conditions)
            )
            or 0
        )
        local_leads = int(
            await session.scalar(select(func.count()).select_from(Lead).where(*lead_conditions)) or 0
        )
        leads_without_delivery = int(
            await session.scalar(
                select(func.count())
                .select_from(Lead)
                .outerjoin(CRMDelivery, CRMDelivery.lead_id == Lead.id)
                .where(*lead_conditions, CRMDelivery.id.is_(None))
            )
            or 0
        )

        delivery_status_rows = (
            await session.execute(
                select(CRMDelivery.status, func.count())
                .join(Lead, Lead.id == CRMDelivery.lead_id)
                .where(*lead_conditions)
                .group_by(CRMDelivery.status)
            )
        ).all()
        by_status = {status.value: 0 for status in CRMDeliveryStatus}
        for status, count in delivery_status_rows:
            by_status[str(status)] = int(count)

        open_dead_letters = int(
            await session.scalar(
                select(func.count())
                .select_from(IntegrationDeadLetter)
                .join(CRMDelivery, CRMDelivery.id == IntegrationDeadLetter.delivery_id)
                .join(Lead, Lead.id == CRMDelivery.lead_id)
                .where(
                    IntegrationDeadLetter.tenant_id == tenant_id,
                    IntegrationDeadLetter.status == "open",
                    *lead_conditions,
                )
            )
            or 0
        )
        counts = CRMWorkflowCountsOut(
            resolved_conversations=resolved_conversations,
            local_leads=local_leads,
            leads_without_delivery=leads_without_delivery,
            total_deliveries=sum(by_status.values()),
            in_flight_deliveries=sum(by_status[status] for status in _IN_FLIGHT_STATUSES),
            verified_deliveries=by_status[CRMDeliveryStatus.VERIFIED.value],
            attention_deliveries=sum(by_status[status] for status in _ATTENTION_STATUSES),
            open_dead_letters=open_dead_letters,
            by_status=by_status,
        )

        lead_rows = (
            await session.execute(
                select(Lead, LeadProfile, Conversation, Agent)
                .join(Agent, Agent.id == Lead.agent_id)
                .outerjoin(
                    LeadProfile,
                    (LeadProfile.lead_id == Lead.id) & (LeadProfile.tenant_id == Lead.tenant_id),
                )
                .outerjoin(Conversation, Conversation.id == Lead.conversation_id)
                .where(*lead_conditions)
                .order_by(Lead.created_at.desc())
                .limit(limit)
            )
        ).all()
        lead_ids = [lead.id for lead, _, _, _ in lead_rows]

        latest_delivery_by_lead: dict[UUID, tuple[CRMDelivery, CRMConnection]] = {}
        open_dead_letter_delivery_ids: set[UUID] = set()
        if lead_ids:
            delivery_rows = (
                await session.execute(
                    select(CRMDelivery, CRMConnection)
                    .join(CRMConnection, CRMConnection.id == CRMDelivery.connection_id)
                    .where(
                        CRMDelivery.tenant_id == tenant_id,
                        CRMDelivery.lead_id.in_(lead_ids),
                    )
                    .order_by(CRMDelivery.created_at.desc())
                )
            ).all()
            for delivery, connection in delivery_rows:
                latest_delivery_by_lead.setdefault(delivery.lead_id, (delivery, connection))

            latest_delivery_ids = [delivery.id for delivery, _ in latest_delivery_by_lead.values()]
            if latest_delivery_ids:
                open_dead_letter_delivery_ids = {
                    delivery_id
                    for delivery_id in await session.scalars(
                        select(IntegrationDeadLetter.delivery_id).where(
                            IntegrationDeadLetter.tenant_id == tenant_id,
                            IntegrationDeadLetter.status == "open",
                            IntegrationDeadLetter.delivery_id.in_(latest_delivery_ids),
                        )
                    )
                    if delivery_id is not None
                }

        recent_journeys: list[CRMWorkflowJourneyOut] = []
        for lead, profile, conversation, agent in lead_rows:
            delivery_pair = latest_delivery_by_lead.get(lead.id)
            delivery = delivery_pair[0] if delivery_pair else None
            connection = delivery_pair[1] if delivery_pair else None
            dead_letter_open = bool(delivery and delivery.id in open_dead_letter_delivery_ids)
            stage, stage_label, stage_detail, action_label, action_path = _journey_state(
                delivery,
                has_connections=has_connections,
                has_mapping=has_mapping,
                has_route=has_route,
                auto_sync_enabled=auto_sync_enabled,
                dead_letter_open=dead_letter_open,
            )
            delivery_out = (
                CRMWorkflowDeliveryOut(
                    id=delivery.id,
                    connection_id=delivery.connection_id,
                    connection_name=connection.name,
                    provider=delivery.provider,
                    operation=delivery.operation,
                    status=delivery.status,
                    verification_status=delivery.verification_status,
                    external_record_id=delivery.external_record_id,
                    attempt_count=delivery.attempt_count,
                    verification_attempt_count=delivery.verification_attempt_count,
                    acknowledged_at=delivery.acknowledged_at,
                    verified_at=delivery.verified_at,
                    next_retry_at=delivery.next_retry_at,
                    next_verification_at=delivery.next_verification_at,
                    last_error_code=delivery.last_error_code,
                    last_error_message=delivery.last_error_message,
                    verification_error_code=delivery.verification_error_code,
                    verification_error_message=delivery.verification_error_message,
                    dead_letter_open=dead_letter_open,
                    created_at=delivery.created_at,
                    updated_at=delivery.updated_at,
                )
                if delivery and connection
                else None
            )
            recent_journeys.append(
                CRMWorkflowJourneyOut(
                    lead_id=lead.id,
                    conversation_id=lead.conversation_id,
                    conversation_public_id=(conversation.public_id if conversation is not None else None),
                    agent_id=lead.agent_id,
                    agent_name=agent.name,
                    customer_name=lead.name,
                    email=lead.email,
                    phone=lead.phone,
                    source_channel=(
                        profile.source_channel
                        if profile is not None
                        else (conversation.channel.value if conversation is not None else None)
                    ),
                    lifecycle_status=(profile.lifecycle_status if profile is not None else lead.status),
                    qualification_status=(profile.qualification_status if profile is not None else None),
                    qualification_score=(profile.qualification_score if profile is not None else None),
                    stage=stage,
                    stage_label=stage_label,
                    stage_detail=stage_detail,
                    next_action_label=action_label,
                    next_action_path=action_path,
                    delivery=delivery_out,
                    created_at=lead.created_at,
                    updated_at=lead.updated_at,
                )
            )

        return CRMWorkflowOut(
            generated_at=datetime.now(UTC),
            workspace_id=workspace_id,
            readiness=CRMWorkflowReadinessOut(
                ready=workflow_ready,
                stages=readiness_stages,
            ),
            counts=counts,
            connections=connections,
            recent_journeys=recent_journeys,
        )


crm_workflow_service = CRMWorkflowService()
