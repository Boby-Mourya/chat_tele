from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base
from northstar_api.lead_crm.domain import (
    ChannelProvider,
    CRMConnectionStatus,
    CRMDeliveryStatus,
    CRMOperation,
    CRMProvider,
    IdentityType,
    IntegrationHealthStatus,
    LeadLifecycleStatus,
    QualificationStatus,
)

JSONType = JSON().with_variant(JSONB, "postgresql")
MutableJSON = MutableDict.as_mutable(JSONType)


def _enum_value(value: object) -> str:
    return str(getattr(value, "value", value))


class LeadCRMUUIDMixin:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)


class LeadCRMTimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Contact(Base, LeadCRMUUIDMixin, LeadCRMTimestampMixin):
    __tablename__ = "contacts"
    __table_args__ = (
        Index("ix_contacts_tenant_email", "tenant_id", "normalized_email"),
        Index("ix_contacts_tenant_phone", "tenant_id", "normalized_phone"),
        Index("ix_contacts_tenant_activity", "tenant_id", "last_activity_at"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    display_name: Mapped[str | None] = mapped_column(String(160))
    first_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    primary_email: Mapped[str | None] = mapped_column(String(320))
    normalized_email: Mapped[str | None] = mapped_column(String(320))
    primary_phone: Mapped[str | None] = mapped_column(String(80))
    normalized_phone: Mapped[str | None] = mapped_column(String(80))
    company: Mapped[str | None] = mapped_column(String(240))
    job_title: Mapped[str | None] = mapped_column(String(160))
    attributes_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class ContactIdentity(Base, LeadCRMUUIDMixin, LeadCRMTimestampMixin):
    __tablename__ = "contact_identities"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "identity_type", "normalized_value", name="uq_contact_identity_normalized"
        ),
        UniqueConstraint(
            "tenant_id", "provider", "external_id", name="uq_contact_identity_provider_external"
        ),
        Index("ix_contact_identities_contact", "tenant_id", "contact_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    contact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), index=True)
    identity_type: Mapped[str] = mapped_column(String(40), default=IdentityType.CUSTOM.value)
    provider: Mapped[str | None] = mapped_column(String(60))
    normalized_value: Mapped[str | None] = mapped_column(String(512))
    external_id: Mapped[str | None] = mapped_column(String(512))
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)


class RawWebhookEvent(Base, LeadCRMUUIDMixin):
    __tablename__ = "raw_webhook_events"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "provider",
            "connection_key",
            "external_event_id",
            name="uq_raw_webhook_provider_event",
        ),
        Index("ix_raw_webhook_processing", "processing_status", "received_at"),
        Index("ix_raw_webhook_scope", "tenant_id", "provider", "received_at"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    connection_key: Mapped[str] = mapped_column(String(160), default="default")
    provider: Mapped[str] = mapped_column(String(60), default=ChannelProvider.CUSTOM.value)
    external_event_id: Mapped[str] = mapped_column(String(512))
    event_type: Mapped[str] = mapped_column(String(160))
    payload_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)
    headers_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)
    payload_hash: Mapped[str] = mapped_column(String(64))
    verification_status: Mapped[str] = mapped_column(String(40), default="pending")
    processing_status: Mapped[str] = mapped_column(String(40), default="received")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(1000))
    correlation_id: Mapped[str] = mapped_column(String(128), index=True)


class LeadProfile(Base, LeadCRMUUIDMixin, LeadCRMTimestampMixin):
    """Backward-compatible production extension for the existing `leads` row."""

    __tablename__ = "lead_profiles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "lead_id", name="uq_lead_profile_lead"),
        UniqueConstraint("tenant_id", "public_id", name="uq_lead_profile_public_id"),
        Index("ix_lead_profiles_source", "tenant_id", "source_channel", "source_provider"),
        Index("ix_lead_profiles_qualification", "tenant_id", "qualification_status", "qualification_score"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"), index=True
    )
    public_id: Mapped[str] = mapped_column(String(64), default=lambda: f"lead_{uuid.uuid4().hex}")
    first_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    normalized_email: Mapped[str | None] = mapped_column(String(320), index=True)
    normalized_phone: Mapped[str | None] = mapped_column(String(80), index=True)
    company: Mapped[str | None] = mapped_column(String(240))
    job_title: Mapped[str | None] = mapped_column(String(160))
    lifecycle_status: Mapped[str] = mapped_column(String(40), default=LeadLifecycleStatus.NEW.value)
    qualification_status: Mapped[str] = mapped_column(String(40), default=QualificationStatus.PENDING.value)
    qualification_score: Mapped[int] = mapped_column(Integer, default=0)
    qualification_reason: Mapped[str | None] = mapped_column(String(1000))
    source_channel: Mapped[str | None] = mapped_column(String(60))
    source_provider: Mapped[str | None] = mapped_column(String(60))
    source_connection_id: Mapped[str | None] = mapped_column(String(160))
    source_external_id: Mapped[str | None] = mapped_column(String(512))
    campaign: Mapped[str | None] = mapped_column(String(240))
    campaign_id: Mapped[str | None] = mapped_column(String(240))
    ad_id: Mapped[str | None] = mapped_column(String(240))
    adset_id: Mapped[str | None] = mapped_column(String(240))
    utm_source: Mapped[str | None] = mapped_column(String(240))
    utm_medium: Mapped[str | None] = mapped_column(String(240))
    utm_campaign: Mapped[str | None] = mapped_column(String(240))
    utm_term: Mapped[str | None] = mapped_column(String(240))
    utm_content: Mapped[str | None] = mapped_column(String(500))
    consent_status: Mapped[str] = mapped_column(String(40), default="unknown")
    custom_fields_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)
    first_touch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_touch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    qualified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    converted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LeadConsent(Base, LeadCRMUUIDMixin, LeadCRMTimestampMixin):
    __tablename__ = "lead_consents"
    __table_args__ = (Index("ix_lead_consents_scope", "tenant_id", "lead_id", "consent_type"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"), index=True
    )
    consent_type: Mapped[str] = mapped_column(String(80), default="processing")
    status: Mapped[str] = mapped_column(String(40))
    source: Mapped[str | None] = mapped_column(String(80))
    channel: Mapped[str | None] = mapped_column(String(60))
    text_version: Mapped[str | None] = mapped_column(String(120))
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)


class CRMConnection(Base, LeadCRMUUIDMixin, LeadCRMTimestampMixin):
    __tablename__ = "crm_connections"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_crm_connection_name"),
        UniqueConstraint("tenant_id", "public_id", name="uq_crm_connection_public_id"),
        Index("ix_crm_connections_provider", "tenant_id", "provider", "status"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    public_id: Mapped[str] = mapped_column(String(64), default=lambda: f"crm_{uuid.uuid4().hex}")
    provider: Mapped[str] = mapped_column(String(60), default=CRMProvider.GENERIC_REST.value)
    name: Mapped[str] = mapped_column(String(160))
    environment: Mapped[str] = mapped_column(String(40), default="production")
    region: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40), default=CRMConnectionStatus.DRAFT.value)
    credentials_ref: Mapped[str | None] = mapped_column(String(500))
    credentials_encrypted: Mapped[bytes | None] = mapped_column(nullable=True)
    configuration_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)
    capabilities_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)
    last_authenticated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_health_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(1000))


class CRMFieldSchema(Base, LeadCRMUUIDMixin, LeadCRMTimestampMixin):
    __tablename__ = "crm_field_schema"
    __table_args__ = (
        UniqueConstraint("tenant_id", "connection_id", "object_name", "api_name", name="uq_crm_field_schema"),
        Index("ix_crm_field_schema_connection", "tenant_id", "connection_id", "object_name"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("crm_connections.id", ondelete="CASCADE"), index=True
    )
    object_name: Mapped[str] = mapped_column(String(120), default="Leads")
    api_name: Mapped[str] = mapped_column(String(240))
    display_label: Mapped[str] = mapped_column(String(240))
    data_type: Mapped[str] = mapped_column(String(80))
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    nullable: Mapped[bool] = mapped_column(Boolean, default=True)
    read_only: Mapped[bool] = mapped_column(Boolean, default=False)
    unique: Mapped[bool] = mapped_column(Boolean, default=False)
    custom: Mapped[bool] = mapped_column(Boolean, default=False)
    max_length: Mapped[int | None] = mapped_column(Integer)
    picklist_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)
    schema_hash: Mapped[str | None] = mapped_column(String(64))
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CRMFieldMapping(Base, LeadCRMUUIDMixin, LeadCRMTimestampMixin):
    __tablename__ = "crm_field_mappings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "connection_id", "object_name", name="uq_crm_field_mapping_object"),
        Index("ix_crm_field_mapping_connection", "tenant_id", "connection_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("crm_connections.id", ondelete="CASCADE"), index=True
    )
    object_name: Mapped[str] = mapped_column(String(120), default="Leads")
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(40), default="draft")
    mapping_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)
    validation_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)
    schema_hash: Mapped[str | None] = mapped_column(String(64))


class CRMRoute(Base, LeadCRMUUIDMixin, LeadCRMTimestampMixin):
    __tablename__ = "crm_routes"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_crm_route_name"),
        Index("ix_crm_routes_active", "tenant_id", "enabled", "priority"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    version: Mapped[int] = mapped_column(Integer, default=1)
    conditions_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)
    actions_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)


class CRMDelivery(Base, LeadCRMUUIDMixin, LeadCRMTimestampMixin):
    __tablename__ = "crm_deliveries"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_crm_delivery_idempotency"),
        Index("ix_crm_delivery_dispatch", "status", "next_retry_at", "created_at"),
        Index("ix_crm_delivery_verification_dispatch", "verification_status", "next_verification_at"),
        Index("ix_crm_delivery_lead", "tenant_id", "lead_id", "created_at"),
        Index("ix_crm_delivery_connection", "tenant_id", "connection_id", "status"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("crm_connections.id", ondelete="RESTRICT"), index=True
    )
    provider: Mapped[str] = mapped_column(String(60))
    operation: Mapped[str] = mapped_column(String(40), default=CRMOperation.UPSERT.value)
    idempotency_key: Mapped[str] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(40), default=CRMDeliveryStatus.CREATED.value)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    external_record_id: Mapped[str | None] = mapped_column(String(512), index=True)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_error_code: Mapped[str | None] = mapped_column(String(80))
    last_error_message: Mapped[str | None] = mapped_column(String(1000))
    provider_http_status: Mapped[int | None] = mapped_column(Integer)
    provider_code: Mapped[str | None] = mapped_column(String(160))
    provider_request_id: Mapped[str | None] = mapped_column(String(240))
    retry_cycle_attempts: Mapped[int] = mapped_column(Integer, default=0)
    payload_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)
    verification_status: Mapped[str] = mapped_column(String(40), default="pending")
    verification_attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    verification_cycle_attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_verification_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification_error_code: Mapped[str | None] = mapped_column(String(80))
    verification_error_message: Mapped[str | None] = mapped_column(String(1000))
    verification_evidence_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)
    mapping_version: Mapped[int] = mapped_column(Integer, default=1)
    payload_hash: Mapped[str | None] = mapped_column(String(64))
    correlation_id: Mapped[str | None] = mapped_column(String(128), index=True)


class CRMDeliveryAttempt(Base, LeadCRMUUIDMixin):
    __tablename__ = "crm_delivery_attempts"
    __table_args__ = (
        UniqueConstraint("delivery_id", "attempt_number", name="uq_crm_delivery_attempt_number"),
        Index("ix_crm_delivery_attempt_scope", "tenant_id", "delivery_id", "attempt_number"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    delivery_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("crm_deliveries.id", ondelete="CASCADE"), index=True
    )
    attempt_number: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    http_status: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    result_status: Mapped[str | None] = mapped_column(String(80))
    normalized_error_code: Mapped[str | None] = mapped_column(String(80))
    provider_error_code: Mapped[str | None] = mapped_column(String(160))
    provider_request_id: Mapped[str | None] = mapped_column(String(240))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)


class CRMExternalReference(Base, LeadCRMUUIDMixin, LeadCRMTimestampMixin):
    __tablename__ = "crm_external_references"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "connection_id", "object_name", "external_id", name="uq_crm_external_reference"
        ),
        UniqueConstraint(
            "tenant_id", "lead_id", "connection_id", "object_name", name="uq_crm_external_lead_connection"
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("crm_connections.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(60))
    object_name: Mapped[str] = mapped_column(String(120), default="Leads")
    external_id: Mapped[str] = mapped_column(String(512))
    external_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sync_version: Mapped[int] = mapped_column(Integer, default=1)
    change_origin: Mapped[str] = mapped_column(String(60), default="platform")


class CRMWebhookEvent(Base, LeadCRMUUIDMixin):
    __tablename__ = "crm_webhook_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "connection_id", "external_event_id", name="uq_crm_webhook_event"),
        Index("ix_crm_webhook_processing", "processing_status", "received_at"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("crm_connections.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(60))
    external_event_id: Mapped[str] = mapped_column(String(512))
    event_type: Mapped[str] = mapped_column(String(160))
    verification_status: Mapped[str] = mapped_column(String(40), default="pending")
    processing_status: Mapped[str] = mapped_column(String(40), default="received")
    payload_hash: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)
    correlation_id: Mapped[str] = mapped_column(String(128), index=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(1000))


class IntegrationHealthSnapshot(Base, LeadCRMUUIDMixin):
    __tablename__ = "integration_health_snapshots"
    __table_args__ = (Index("ix_integration_health_scope", "tenant_id", "connection_id", "checked_at"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("crm_connections.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(40), default=IntegrationHealthStatus.UNKNOWN.value)
    checks_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class IntegrationDeadLetter(Base, LeadCRMUUIDMixin, LeadCRMTimestampMixin):
    __tablename__ = "integration_dead_letters"
    __table_args__ = (Index("ix_integration_dead_letter_scope", "tenant_id", "status", "created_at"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    delivery_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("crm_deliveries.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(String(40), default="open")
    reason_code: Mapped[str | None] = mapped_column(String(80))
    reason_message: Mapped[str | None] = mapped_column(String(1000))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LeadActivityEvent(Base, LeadCRMUUIDMixin):
    __tablename__ = "lead_activity_events"
    __table_args__ = (Index("ix_lead_activity_scope", "tenant_id", "lead_id", "occurred_at"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(160))
    actor_type: Mapped[str] = mapped_column(String(60), default="system")
    actor_id: Mapped[str | None] = mapped_column(String(160))
    correlation_id: Mapped[str | None] = mapped_column(String(128), index=True)
    details_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
