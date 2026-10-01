from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.lead_crm.domain import (
    CRMDeliveryStatus,
    CRMOperation,
    LeadLifecycleStatus,
    QualificationStatus,
)
from northstar_api.lead_crm.mapping import canonical_lead
from northstar_api.lead_crm.models import (
    Contact,
    ContactIdentity,
    CRMConnection,
    CRMDelivery,
    CRMFieldMapping,
    CRMRoute,
    LeadActivityEvent,
    LeadProfile,
)
from northstar_api.lead_crm.normalization import normalize_identity
from northstar_api.models import Lead
from northstar_api.services.education_conversation_policy import is_education_lead
from northstar_api.services.outbox import enqueue_event


def _stable_json(value: dict[str, Any]) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True, default=str)


def _payload_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(_stable_json(value).encode()).hexdigest()


class IdentityService:
    async def resolve_or_create_contact(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        name: str | None,
        email: str | None,
        phone: str | None,
        provider: str | None = None,
        provider_external_id: str | None = None,
        company: str | None = None,
        job_title: str | None = None,
    ) -> Contact:
        normalized = normalize_identity(email, phone)
        predicates = []
        if normalized.email:
            predicates.append(Contact.normalized_email == normalized.email)
        if normalized.phone:
            predicates.append(Contact.normalized_phone == normalized.phone)
        contact: Contact | None = None
        if predicates:
            contact = await session.scalar(
                select(Contact).where(Contact.tenant_id == tenant_id, or_(*predicates))
            )
        if contact is None and provider and provider_external_id:
            identity = await session.scalar(
                select(ContactIdentity).where(
                    ContactIdentity.tenant_id == tenant_id,
                    ContactIdentity.provider == provider,
                    ContactIdentity.external_id == provider_external_id,
                )
            )
            if identity:
                contact = await session.scalar(
                    select(Contact).where(Contact.id == identity.contact_id, Contact.tenant_id == tenant_id)
                )
        if contact is None:
            first_name = None
            last_name = None
            if name:
                parts = name.strip().split(None, 1)
                first_name = parts[0] if parts else None
                last_name = parts[1] if len(parts) > 1 else None
            candidate = Contact(
                tenant_id=tenant_id,
                display_name=name,
                first_name=first_name,
                last_name=last_name,
                primary_email=email,
                normalized_email=normalized.email,
                primary_phone=phone,
                normalized_phone=normalized.phone,
                company=company,
                job_title=job_title,
                last_activity_at=datetime.now(UTC),
            )
            try:
                async with session.begin_nested():
                    session.add(candidate)
                    await session.flush()
                contact = candidate
            except IntegrityError:
                retry_predicates = []
                if normalized.email:
                    retry_predicates.append(Contact.normalized_email == normalized.email)
                if normalized.phone:
                    retry_predicates.append(Contact.normalized_phone == normalized.phone)
                contact = (
                    await session.scalar(
                        select(Contact).where(Contact.tenant_id == tenant_id, or_(*retry_predicates))
                    )
                    if retry_predicates
                    else None
                )
                if contact is None:
                    raise
        else:
            contact.last_activity_at = datetime.now(UTC)
            if name and not contact.display_name:
                contact.display_name = name
            if email and not contact.primary_email:
                contact.primary_email = email
                contact.normalized_email = normalized.email
            if phone and not contact.primary_phone:
                contact.primary_phone = phone
                contact.normalized_phone = normalized.phone

        identities: list[tuple[str, str | None, str | None]] = []
        if normalized.email:
            identities.append(("email", None, normalized.email))
        if normalized.phone:
            identities.append(("phone", None, normalized.phone))
        if provider and provider_external_id:
            identities.append((provider, provider, provider_external_id))
        for identity_type, identity_provider, value in identities:
            if not value:
                continue
            exists = await session.scalar(
                select(ContactIdentity.id).where(
                    ContactIdentity.tenant_id == tenant_id,
                    ContactIdentity.contact_id == contact.id,
                    ContactIdentity.identity_type == identity_type,
                    ContactIdentity.normalized_value == (value if identity_provider is None else None),
                    ContactIdentity.external_id == (value if identity_provider else None),
                )
            )
            if exists is None:
                identity = ContactIdentity(
                    tenant_id=tenant_id,
                    contact_id=contact.id,
                    identity_type=identity_type,
                    provider=identity_provider,
                    normalized_value=value if identity_provider is None else None,
                    external_id=value if identity_provider else None,
                    verified=False,
                )
                try:
                    async with session.begin_nested():
                        session.add(identity)
                        await session.flush()
                except IntegrityError:
                    pass
        await session.flush()
        return contact


class LeadDomainService:
    def __init__(self) -> None:
        self.identity = IdentityService()

    async def ensure_profile(
        self,
        session: AsyncSession,
        *,
        lead: Lead,
        source_channel: str | None = None,
        source_provider: str | None = None,
        source_connection_id: str | None = None,
        source_external_id: str | None = None,
    ) -> LeadProfile:
        profile = await session.scalar(
            select(LeadProfile).where(LeadProfile.tenant_id == lead.tenant_id, LeadProfile.lead_id == lead.id)
        )
        if profile:
            return profile
        normalized = normalize_identity(lead.email, lead.phone)
        contact = await self.identity.resolve_or_create_contact(
            session,
            tenant_id=lead.tenant_id,
            name=lead.name,
            email=lead.email,
            phone=lead.phone,
            provider=source_provider,
            provider_external_id=source_external_id,
        )
        first_name = None
        last_name = None
        if lead.name:
            parts = lead.name.strip().split(None, 1)
            first_name = parts[0] if parts else None
            last_name = parts[1] if len(parts) > 1 else None
        candidate = LeadProfile(
            tenant_id=lead.tenant_id,
            lead_id=lead.id,
            contact_id=contact.id,
            public_id=f"lead_{uuid.uuid4().hex}",
            first_name=first_name,
            last_name=last_name,
            normalized_email=normalized.email,
            normalized_phone=normalized.phone,
            lifecycle_status=lead.status
            if lead.status in {item.value for item in LeadLifecycleStatus}
            else LeadLifecycleStatus.NEW.value,
            qualification_status=(
                QualificationStatus.QUALIFIED.value
                if lead.status == LeadLifecycleStatus.QUALIFIED.value
                else QualificationStatus.PENDING.value
            ),
            consent_status="granted" if lead.consent else "unknown",
            custom_fields_json=dict(lead.fields_json or {}),
            source_channel=source_channel,
            source_provider=source_provider,
            source_connection_id=source_connection_id,
            source_external_id=source_external_id,
            utm_source=(lead.fields_json or {}).get("utm_source"),
            utm_medium=(lead.fields_json or {}).get("utm_medium"),
            utm_campaign=(lead.fields_json or {}).get("utm_campaign"),
            utm_term=(lead.fields_json or {}).get("utm_term"),
            utm_content=(lead.fields_json or {}).get("utm_content"),
            first_touch_at=lead.created_at,
            last_touch_at=lead.updated_at,
        )
        try:
            async with session.begin_nested():
                session.add(candidate)
                await session.flush()
            profile = candidate
        except IntegrityError:
            existing_profile = await session.scalar(
                select(LeadProfile).where(
                    LeadProfile.tenant_id == lead.tenant_id,
                    LeadProfile.lead_id == lead.id,
                )
            )
            if existing_profile is None:
                raise
            return existing_profile
        session.add(
            LeadActivityEvent(
                tenant_id=lead.tenant_id,
                lead_id=lead.id,
                event_type="lead.profile.created.v1",
                details_json={"contactId": str(contact.id), "publicId": candidate.public_id},
            )
        )
        return candidate

    async def update_status(
        self,
        session: AsyncSession,
        *,
        lead: Lead,
        status: LeadLifecycleStatus,
        actor_id: str | None,
        correlation_id: str | None,
        qualification_reason: str = "Marked Qualified in Leads",
        skip_unchanged: bool = False,
    ) -> None:
        profile = await self.ensure_profile(session, lead=lead)
        if skip_unchanged and lead.status == status.value and (
            status != LeadLifecycleStatus.QUALIFIED
            or profile.qualification_status == QualificationStatus.QUALIFIED.value
        ):
            return
        previous = lead.status
        lead.status = status.value
        profile.lifecycle_status = status.value
        qualification_requested = status.value == LeadLifecycleStatus.QUALIFIED.value
        if qualification_requested and (
            previous != status.value or profile.qualification_status != QualificationStatus.QUALIFIED.value
        ):
            await self.qualify(
                session,
                lead=lead,
                score=profile.qualification_score,
                reason=qualification_reason,
                actor_id=actor_id,
                correlation_id=correlation_id,
            )
        else:
            if status.value in {LeadLifecycleStatus.UNQUALIFIED.value, LeadLifecycleStatus.LOST.value}:
                profile.qualification_status = QualificationStatus.UNQUALIFIED.value
                profile.qualified_at = None
            elif status.value not in {LeadLifecycleStatus.QUALIFIED.value, LeadLifecycleStatus.CONVERTED.value}:
                profile.qualification_status = QualificationStatus.PENDING.value
                profile.qualified_at = None
            await self.request_sync(
                session, lead=lead, reason="qualification" if qualification_requested else "lead_updated",
                actor_id=actor_id, correlation_id=correlation_id,
            )
        session.add(
            LeadActivityEvent(
                tenant_id=lead.tenant_id,
                lead_id=lead.id,
                event_type="lead.status.changed.v1",
                actor_type="user" if actor_id else "system",
                actor_id=actor_id,
                correlation_id=correlation_id,
                details_json={"previousStatus": previous, "status": status.value},
            )
        )
        enqueue_event(
            session,
            tenant_id=lead.tenant_id,
            aggregate_type="lead",
            aggregate_id=lead.id,
            event_type="lead.updated.v1",
            payload={
                "leadId": str(lead.id),
                "workspaceId": str(lead.workspace_id),
                "previousStatus": previous,
                "status": status.value,
            },
        )

    async def qualify(
        self,
        session: AsyncSession,
        *,
        lead: Lead,
        score: int,
        reason: str,
        actor_id: str | None,
        correlation_id: str | None,
    ) -> LeadProfile:
        profile = await self.ensure_profile(session, lead=lead)
        profile.lifecycle_status = LeadLifecycleStatus.QUALIFIED.value
        profile.qualification_status = QualificationStatus.QUALIFIED.value
        profile.qualification_score = max(0, min(score, 100))
        profile.qualification_reason = reason[:1000]
        profile.qualified_at = datetime.now(UTC)
        lead.status = LeadLifecycleStatus.QUALIFIED.value
        session.add(
            LeadActivityEvent(
                tenant_id=lead.tenant_id,
                lead_id=lead.id,
                event_type="lead.qualified.v1",
                actor_type="user" if actor_id else "system",
                actor_id=actor_id,
                correlation_id=correlation_id,
                details_json={"score": profile.qualification_score, "reason": profile.qualification_reason},
            )
        )
        enqueue_event(
            session,
            tenant_id=lead.tenant_id,
            aggregate_type="lead",
            aggregate_id=lead.id,
            event_type="lead.qualified.v1",
            payload={"leadId": str(lead.id), "score": profile.qualification_score},
        )
        enqueue_event(
            session,
            tenant_id=lead.tenant_id,
            aggregate_type="lead",
            aggregate_id=lead.id,
            event_type="lead.crm.sync.requested.v1",
            payload={"leadId": str(lead.id), "reason": "qualification"},
        )
        return profile

    async def request_sync(
        self,
        session: AsyncSession,
        *,
        lead: Lead,
        reason: str,
        correlation_id: str | None,
        actor_id: str | None = None,
    ) -> None:
        await self.ensure_profile(session, lead=lead)
        session.add(
            LeadActivityEvent(
                tenant_id=lead.tenant_id,
                lead_id=lead.id,
                event_type="lead.crm.sync.requested.v1",
                actor_type="user" if actor_id else "system",
                actor_id=actor_id,
                correlation_id=correlation_id,
                details_json={"reason": reason},
            )
        )
        enqueue_event(
            session,
            tenant_id=lead.tenant_id,
            aggregate_type="lead",
            aggregate_id=lead.id,
            event_type="lead.crm.sync.requested.v1",
            payload={"leadId": str(lead.id), "reason": reason},
        )


class CRMRouteService:
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
    ) -> list[CRMDelivery]:
        lead = await session.scalar(select(Lead).where(Lead.id == lead_id, Lead.tenant_id == tenant_id))
        if not lead:
            raise ValueError("Lead does not exist in tenant scope")
        if await is_education_lead(session, lead.id):
            return []
        profile = await session.scalar(
            select(LeadProfile).where(LeadProfile.tenant_id == tenant_id, LeadProfile.lead_id == lead_id)
        )
        if not profile:
            profile = await lead_domain_service.ensure_profile(session, lead=lead)
        routes = list(
            await session.scalars(
                select(CRMRoute)
                .where(CRMRoute.tenant_id == tenant_id, CRMRoute.enabled.is_(True))
                .order_by(CRMRoute.priority, CRMRoute.created_at)
            )
        )
        connection_ids: list[UUID] = []
        for route in routes:
            if not self._matches(route, profile, lead):
                continue
            raw_ids = (route.actions_json or {}).get("connectionIds", [])
            for raw in raw_ids:
                try:
                    value = UUID(str(raw))
                except ValueError:
                    continue
                if value not in connection_ids:
                    connection_ids.append(value)
        deliveries: list[CRMDelivery] = []
        for connection_id in connection_ids:
            connection = await session.scalar(
                select(CRMConnection).where(
                    CRMConnection.id == connection_id,
                    CRMConnection.tenant_id == tenant_id,
                    CRMConnection.status.not_in(("disabled", "configuration_error")),
                )
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
            idempotency_key = f"{tenant_id}:{lead_id}:{connection.id}:upsert:{digest}"
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
                    details_json={"connectionId": str(connection.id), "provider": connection.provider},
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
                    "deliveryId": str(delivery.id),
                    "connectionId": str(connection.id),
                    "provider": connection.provider,
                },
            )
            deliveries.append(delivery)
        return deliveries


lead_domain_service = LeadDomainService()
crm_route_service = CRMRouteService()
