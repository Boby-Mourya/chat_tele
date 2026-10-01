from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.lead_crm.domain import CRMDeliveryStatus, CRMOperation, LeadLifecycleStatus
from northstar_api.lead_crm.models import (
    CRMConnection,
    CRMDelivery,
    CRMExternalReference,
    CRMFieldMapping,
    CRMRoute,
    LeadActivityEvent,
    LeadProfile,
)
from northstar_api.lead_crm.services import _payload_hash, canonical_lead, lead_domain_service
from northstar_api.lead_crm.workspace_scope import WorkspaceCRMConnection, WorkspaceCRMRoute
from northstar_api.models import Conversation, ConversationState, Lead
from northstar_api.services.education_conversation_policy import is_education_lead
from northstar_api.services.outbox import enqueue_event


class WorkspaceCRMRouteService:
    """Create CRM deliveries using only routes and credentials from Lead.workspace_id."""

    def _matches(self, route: CRMRoute, profile: LeadProfile, lead: Lead) -> bool:
        conditions = route.conditions_json or {}
        if not conditions:
            return True
        values: dict[str, Any] = {
            "channel": profile.source_channel,
            "provider": profile.source_provider,
            "campaign": profile.campaign,
            "qualificationStatus": profile.qualification_status,
            "minimumScore": profile.qualification_score,
            "agentId": str(lead.agent_id),
        }
        for key, expected in conditions.items():
            if key == "minimumScore":
                try:
                    if profile.qualification_score < int(expected):
                        return False
                except (TypeError, ValueError):
                    return False
                continue
            if values.get(key) != expected:
                return False
        return True

    async def create_deliveries(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        lead_id: UUID,
        correlation_id: str | None = None,
        sync_reason: str | None = None,
        origin_connection_id: UUID | None = None,
        target_connection_id: UUID | None = None,
    ) -> list[CRMDelivery]:
        lead = await session.scalar(select(Lead).where(Lead.id == lead_id, Lead.tenant_id == tenant_id))
        if not lead:
            raise ValueError("Lead does not exist in tenant scope")
        if await is_education_lead(session, lead.id):
            return []

        profile = await session.scalar(
            select(LeadProfile).where(
                LeadProfile.tenant_id == tenant_id,
                LeadProfile.lead_id == lead_id,
            )
        )
        if not profile:
            profile = await lead_domain_service.ensure_profile(session, lead=lead)

        synced_connections = set(await session.scalars(select(CRMExternalReference.connection_id).where(
            CRMExternalReference.tenant_id == tenant_id,
            CRMExternalReference.lead_id == lead.id,
            CRMExternalReference.object_name == "Leads",
        )))
        conversation_ready = True
        if lead.conversation_id is not None:
            conversation_state = await session.scalar(select(Conversation.state).where(
                Conversation.id == lead.conversation_id,
                Conversation.tenant_id == tenant_id,
                Conversation.workspace_id == lead.workspace_id,
                Conversation.agent_id == lead.agent_id,
            ))
            conversation_ready = (
                lead.status == LeadLifecycleStatus.QUALIFIED.value
                and conversation_state == ConversationState.RESOLVED
            )

        routes = list(
            await session.scalars(
                select(CRMRoute)
                .join(WorkspaceCRMRoute, WorkspaceCRMRoute.route_id == CRMRoute.id)
                .where(
                    CRMRoute.tenant_id == tenant_id,
                    CRMRoute.enabled.is_(True),
                    WorkspaceCRMRoute.tenant_id == tenant_id,
                    WorkspaceCRMRoute.workspace_id == lead.workspace_id,
                )
                .order_by(CRMRoute.priority, CRMRoute.created_at)
            )
        )

        connection_ids: list[UUID] = []
        for route in routes:
            if not self._matches(route, profile, lead):
                continue
            for raw in (route.actions_json or {}).get("connectionIds", []):
                try:
                    connection_id = UUID(str(raw))
                except ValueError:
                    continue
                if target_connection_id is not None and connection_id != target_connection_id:
                    continue
                if connection_id not in connection_ids:
                    connection_ids.append(connection_id)

        deliveries: list[CRMDelivery] = []
        for connection_id in connection_ids:
            # Initial automatic delivery waits for both workflow steps. Explicit
            # manual sync and updates to existing CRM records retain their behavior.
            if sync_reason != "manual" and connection_id not in synced_connections and not conversation_ready:
                continue
            if origin_connection_id is not None and connection_id == origin_connection_id:
                session.add(
                    LeadActivityEvent(
                        tenant_id=tenant_id,
                        lead_id=lead.id,
                        event_type="lead.crm.delivery.suppressed.v1",
                        correlation_id=correlation_id,
                        details_json={
                            "workspaceId": str(lead.workspace_id),
                            "connectionId": str(connection_id),
                            "reason": "inbound_origin",
                        },
                    )
                )
                continue

            connection_conditions = [
                CRMConnection.id == connection_id,
                CRMConnection.tenant_id == tenant_id,
                CRMConnection.status.not_in(("disabled", "configuration_error")),
                WorkspaceCRMConnection.tenant_id == tenant_id,
                WorkspaceCRMConnection.workspace_id == lead.workspace_id,
            ]
            if sync_reason == "manual":
                pass
            elif sync_reason in {"qualification", "conversation_resolved", "education_upsell_conversation_resolved"}:
                auto_sync = (
                    WorkspaceCRMConnection.auto_sync_updates if connection_id in synced_connections
                    else WorkspaceCRMConnection.auto_sync_new_leads
                )
                connection_conditions.append(auto_sync.is_(True))
            elif sync_reason in (None, "lead_created"):
                connection_conditions.append(WorkspaceCRMConnection.auto_sync_new_leads.is_(True))
            else:
                connection_conditions.append(WorkspaceCRMConnection.auto_sync_updates.is_(True))
            connection = await session.scalar(
                select(CRMConnection)
                .join(
                    WorkspaceCRMConnection,
                    WorkspaceCRMConnection.connection_id == CRMConnection.id,
                )
                .where(*connection_conditions)
            )
            if not connection:
                continue

            mapping = await session.scalar(
                select(CRMFieldMapping).where(
                    CRMFieldMapping.tenant_id == tenant_id,
                    CRMFieldMapping.connection_id == connection.id,
                    CRMFieldMapping.object_name == "Leads",
                )
            )
            payload_basis = canonical_lead(lead, profile)
            payload_basis.pop("createdAt", None)
            payload_basis.pop("updatedAt", None)
            payload_basis["mappingVersion"] = mapping.version if mapping else 0
            digest = _payload_hash(payload_basis)
            idempotency_key = f"{tenant_id}:{lead.workspace_id}:{lead_id}:{connection.id}:upsert:{digest}"
            delivery = await session.scalar(
                select(CRMDelivery).where(
                    CRMDelivery.tenant_id == tenant_id,
                    CRMDelivery.idempotency_key == idempotency_key,
                )
            )
            if delivery:
                deliveries.append(delivery)
                continue

            candidate = CRMDelivery(
                tenant_id=tenant_id,
                lead_id=lead.id,
                connection_id=connection.id,
                provider=connection.provider,
                operation=CRMOperation.UPSERT.value,
                idempotency_key=idempotency_key,
                status=CRMDeliveryStatus.QUEUED.value,
                queued_at=datetime.now(UTC),
                payload_hash=digest,
                mapping_version=mapping.version if mapping else 0,
                correlation_id=correlation_id,
            )
            try:
                async with session.begin_nested():
                    session.add(candidate)
                    await session.flush()
                delivery = candidate
            except IntegrityError:
                delivery = await session.scalar(
                    select(CRMDelivery).where(
                        CRMDelivery.tenant_id == tenant_id,
                        CRMDelivery.idempotency_key == idempotency_key,
                    )
                )
                if delivery is None:
                    raise
                deliveries.append(delivery)
                continue

            session.add(
                LeadActivityEvent(
                    tenant_id=tenant_id,
                    lead_id=lead.id,
                    event_type="lead.crm.delivery.created.v1",
                    correlation_id=correlation_id,
                    details_json={
                        "workspaceId": str(lead.workspace_id),
                        "connectionId": str(connection.id),
                        "provider": connection.provider,
                    },
                )
            )
            enqueue_event(
                session,
                tenant_id=tenant_id,
                aggregate_type="crm_delivery",
                aggregate_id=delivery.id,
                event_type="lead.crm.delivery.created.v1",
                payload={
                    "leadId": str(lead.id),
                    "workspaceId": str(lead.workspace_id),
                    "deliveryId": str(delivery.id),
                    "connectionId": str(connection.id),
                    "provider": connection.provider,
                },
            )
            deliveries.append(delivery)
        return deliveries


workspace_crm_route_service = WorkspaceCRMRouteService()
