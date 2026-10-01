"""Add provider-neutral omnichannel lead and CRM integration persistence.

Revision ID: 0005_lead_crm_platform
Revises: 0004_whatsapp_per_agent
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_lead_crm_platform"
down_revision = "0004_whatsapp_per_agent"
branch_labels = None
depends_on = None

TENANT_TABLES = (
    "contacts",
    "contact_identities",
    "raw_webhook_events",
    "lead_profiles",
    "lead_consents",
    "crm_connections",
    "crm_field_schema",
    "crm_field_mappings",
    "crm_routes",
    "crm_deliveries",
    "crm_delivery_attempts",
    "crm_external_references",
    "crm_webhook_events",
    "integration_health_snapshots",
    "integration_dead_letters",
    "lead_activity_events",
)


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def upgrade() -> None:
    op.create_table(
        "contacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(160)),
        sa.Column("first_name", sa.String(100)),
        sa.Column("last_name", sa.String(100)),
        sa.Column("primary_email", sa.String(320)),
        sa.Column("normalized_email", sa.String(320)),
        sa.Column("primary_phone", sa.String(80)),
        sa.Column("normalized_phone", sa.String(80)),
        sa.Column("company", sa.String(240)),
        sa.Column("job_title", sa.String(160)),
        sa.Column("attributes_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("last_activity_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_contacts_tenant_id", "contacts", ["tenant_id"])
    op.create_index("ix_contacts_tenant_email", "contacts", ["tenant_id", "normalized_email"])
    op.create_index("ix_contacts_tenant_phone", "contacts", ["tenant_id", "normalized_phone"])
    op.create_index("ix_contacts_tenant_activity", "contacts", ["tenant_id", "last_activity_at"])

    op.create_table(
        "contact_identities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=False),
        sa.Column("identity_type", sa.String(40), nullable=False, server_default="custom"),
        sa.Column("provider", sa.String(60)),
        sa.Column("normalized_value", sa.String(512)),
        sa.Column("external_id", sa.String(512)),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "identity_type", "normalized_value", name="uq_contact_identity_normalized"
        ),
        sa.UniqueConstraint(
            "tenant_id", "provider", "external_id", name="uq_contact_identity_provider_external"
        ),
    )
    op.create_index("ix_contact_identities_tenant_id", "contact_identities", ["tenant_id"])
    op.create_index("ix_contact_identities_contact", "contact_identities", ["tenant_id", "contact_id"])

    op.create_table(
        "raw_webhook_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("connection_key", sa.String(160), nullable=False, server_default="default"),
        sa.Column("provider", sa.String(60), nullable=False, server_default="custom"),
        sa.Column("external_event_id", sa.String(512), nullable=False),
        sa.Column("event_type", sa.String(160), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("headers_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("verification_status", sa.String(40), nullable=False, server_default="pending"),
        sa.Column("processing_status", sa.String(40), nullable=False, server_default="received"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(1000)),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "provider",
            "connection_key",
            "external_event_id",
            name="uq_raw_webhook_provider_event",
        ),
    )
    op.create_index("ix_raw_webhook_tenant_id", "raw_webhook_events", ["tenant_id"])
    op.create_index("ix_raw_webhook_processing", "raw_webhook_events", ["processing_status", "received_at"])
    op.create_index("ix_raw_webhook_scope", "raw_webhook_events", ["tenant_id", "provider", "received_at"])
    op.create_index("ix_raw_webhook_correlation", "raw_webhook_events", ["correlation_id"])

    op.create_table(
        "lead_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid()),
        sa.Column("public_id", sa.String(64), nullable=False),
        sa.Column("first_name", sa.String(100)),
        sa.Column("last_name", sa.String(100)),
        sa.Column("normalized_email", sa.String(320)),
        sa.Column("normalized_phone", sa.String(80)),
        sa.Column("company", sa.String(240)),
        sa.Column("job_title", sa.String(160)),
        sa.Column("lifecycle_status", sa.String(40), nullable=False, server_default="new"),
        sa.Column("qualification_status", sa.String(40), nullable=False, server_default="pending"),
        sa.Column("qualification_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("qualification_reason", sa.String(1000)),
        sa.Column("source_channel", sa.String(60)),
        sa.Column("source_provider", sa.String(60)),
        sa.Column("source_connection_id", sa.String(160)),
        sa.Column("source_external_id", sa.String(512)),
        sa.Column("campaign", sa.String(240)),
        sa.Column("campaign_id", sa.String(240)),
        sa.Column("ad_id", sa.String(240)),
        sa.Column("adset_id", sa.String(240)),
        sa.Column("utm_source", sa.String(240)),
        sa.Column("utm_medium", sa.String(240)),
        sa.Column("utm_campaign", sa.String(240)),
        sa.Column("utm_term", sa.String(240)),
        sa.Column("utm_content", sa.String(500)),
        sa.Column("consent_status", sa.String(40), nullable=False, server_default="unknown"),
        sa.Column("custom_fields_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("first_touch_at", sa.DateTime(timezone=True)),
        sa.Column("last_touch_at", sa.DateTime(timezone=True)),
        sa.Column("qualified_at", sa.DateTime(timezone=True)),
        sa.Column("converted_at", sa.DateTime(timezone=True)),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "lead_id", name="uq_lead_profile_lead"),
        sa.UniqueConstraint("tenant_id", "public_id", name="uq_lead_profile_public_id"),
    )
    op.create_index("ix_lead_profiles_tenant_id", "lead_profiles", ["tenant_id"])
    op.create_index("ix_lead_profiles_lead_id", "lead_profiles", ["lead_id"])
    op.create_index("ix_lead_profiles_contact_id", "lead_profiles", ["contact_id"])
    op.create_index("ix_lead_profiles_normalized_email", "lead_profiles", ["normalized_email"])
    op.create_index("ix_lead_profiles_normalized_phone", "lead_profiles", ["normalized_phone"])
    op.create_index(
        "ix_lead_profiles_source", "lead_profiles", ["tenant_id", "source_channel", "source_provider"]
    )
    op.create_index(
        "ix_lead_profiles_qualification",
        "lead_profiles",
        ["tenant_id", "qualification_status", "qualification_score"],
    )

    op.create_table(
        "lead_consents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid()),
        sa.Column("consent_type", sa.String(80), nullable=False, server_default="processing"),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("source", sa.String(80)),
        sa.Column("channel", sa.String(60)),
        sa.Column("text_version", sa.String(120)),
        sa.Column("captured_at", sa.DateTime(timezone=True)),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True)),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lead_consents_tenant_id", "lead_consents", ["tenant_id"])
    op.create_index("ix_lead_consents_scope", "lead_consents", ["tenant_id", "lead_id", "consent_type"])

    op.create_table(
        "crm_connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("public_id", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(60), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("environment", sa.String(40), nullable=False, server_default="production"),
        sa.Column("region", sa.String(80)),
        sa.Column("status", sa.String(40), nullable=False, server_default="draft"),
        sa.Column("credentials_ref", sa.String(500)),
        sa.Column("credentials_encrypted", sa.LargeBinary()),
        sa.Column("configuration_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("capabilities_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("last_authenticated_at", sa.DateTime(timezone=True)),
        sa.Column("last_health_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_failure_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(1000)),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_crm_connection_name"),
        sa.UniqueConstraint("tenant_id", "public_id", name="uq_crm_connection_public_id"),
    )
    op.create_index("ix_crm_connections_tenant_id", "crm_connections", ["tenant_id"])
    op.create_index("ix_crm_connections_provider", "crm_connections", ["tenant_id", "provider", "status"])

    op.create_table(
        "crm_field_schema",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("object_name", sa.String(120), nullable=False, server_default="Leads"),
        sa.Column("api_name", sa.String(240), nullable=False),
        sa.Column("display_label", sa.String(240), nullable=False),
        sa.Column("data_type", sa.String(80), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("nullable", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("read_only", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("unique", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("custom", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("max_length", sa.Integer()),
        sa.Column("picklist_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("schema_hash", sa.String(64)),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connection_id"], ["crm_connections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "connection_id", "object_name", "api_name", name="uq_crm_field_schema"
        ),
    )
    op.create_index("ix_crm_field_schema_tenant_id", "crm_field_schema", ["tenant_id"])
    op.create_index(
        "ix_crm_field_schema_connection", "crm_field_schema", ["tenant_id", "connection_id", "object_name"]
    )

    op.create_table(
        "crm_field_mappings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("object_name", sa.String(120), nullable=False, server_default="Leads"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(40), nullable=False, server_default="draft"),
        sa.Column("mapping_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("validation_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("schema_hash", sa.String(64)),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connection_id"], ["crm_connections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "connection_id", "object_name", name="uq_crm_field_mapping_object"),
    )
    op.create_index("ix_crm_field_mappings_tenant_id", "crm_field_mappings", ["tenant_id"])
    op.create_index("ix_crm_field_mapping_connection", "crm_field_mappings", ["tenant_id", "connection_id"])

    op.create_table(
        "crm_routes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("conditions_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("actions_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_crm_route_name"),
    )
    op.create_index("ix_crm_routes_tenant_id", "crm_routes", ["tenant_id"])
    op.create_index("ix_crm_routes_active", "crm_routes", ["tenant_id", "enabled", "priority"])

    op.create_table(
        "crm_deliveries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(60), nullable=False),
        sa.Column("operation", sa.String(40), nullable=False, server_default="upsert"),
        sa.Column("idempotency_key", sa.String(256), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="created"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("external_record_id", sa.String(512)),
        sa.Column("queued_at", sa.DateTime(timezone=True)),
        sa.Column("processing_at", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("next_retry_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.String(80)),
        sa.Column("last_error_message", sa.String(1000)),
        sa.Column("provider_http_status", sa.Integer()),
        sa.Column("provider_code", sa.String(160)),
        sa.Column("provider_request_id", sa.String(240)),
        sa.Column("mapping_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("payload_hash", sa.String(64)),
        sa.Column("correlation_id", sa.String(128)),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connection_id"], ["crm_connections.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_crm_delivery_idempotency"),
    )
    op.create_index("ix_crm_deliveries_tenant_id", "crm_deliveries", ["tenant_id"])
    op.create_index("ix_crm_delivery_dispatch", "crm_deliveries", ["status", "next_retry_at", "created_at"])
    op.create_index("ix_crm_delivery_lead", "crm_deliveries", ["tenant_id", "lead_id", "created_at"])
    op.create_index("ix_crm_delivery_connection", "crm_deliveries", ["tenant_id", "connection_id", "status"])
    op.create_index("ix_crm_delivery_external_record_id", "crm_deliveries", ["external_record_id"])
    op.create_index("ix_crm_delivery_correlation_id", "crm_deliveries", ["correlation_id"])

    op.create_table(
        "crm_delivery_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("delivery_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("http_status", sa.Integer()),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("result_status", sa.String(80)),
        sa.Column("normalized_error_code", sa.String(80)),
        sa.Column("provider_error_code", sa.String(160)),
        sa.Column("provider_request_id", sa.String(240)),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["delivery_id"], ["crm_deliveries.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("delivery_id", "attempt_number", name="uq_crm_delivery_attempt_number"),
    )
    op.create_index("ix_crm_delivery_attempts_tenant_id", "crm_delivery_attempts", ["tenant_id"])
    op.create_index(
        "ix_crm_delivery_attempt_scope",
        "crm_delivery_attempts",
        ["tenant_id", "delivery_id", "attempt_number"],
    )

    op.create_table(
        "crm_external_references",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(60), nullable=False),
        sa.Column("object_name", sa.String(120), nullable=False, server_default="Leads"),
        sa.Column("external_id", sa.String(512), nullable=False),
        sa.Column("external_modified_at", sa.DateTime(timezone=True)),
        sa.Column("sync_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("change_origin", sa.String(60), nullable=False, server_default="platform"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connection_id"], ["crm_connections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "connection_id", "object_name", "external_id", name="uq_crm_external_reference"
        ),
        sa.UniqueConstraint(
            "tenant_id", "lead_id", "connection_id", "object_name", name="uq_crm_external_lead_connection"
        ),
    )
    op.create_index("ix_crm_external_references_tenant_id", "crm_external_references", ["tenant_id"])
    op.create_index("ix_crm_external_references_lead_id", "crm_external_references", ["lead_id"])
    op.create_index("ix_crm_external_references_connection_id", "crm_external_references", ["connection_id"])

    op.create_table(
        "crm_webhook_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(60), nullable=False),
        sa.Column("external_event_id", sa.String(512), nullable=False),
        sa.Column("event_type", sa.String(160), nullable=False),
        sa.Column("verification_status", sa.String(40), nullable=False, server_default="pending"),
        sa.Column("processing_status", sa.String(40), nullable=False, server_default="received"),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(1000)),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connection_id"], ["crm_connections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "connection_id", "external_event_id", name="uq_crm_webhook_event"),
    )
    op.create_index("ix_crm_webhook_events_tenant_id", "crm_webhook_events", ["tenant_id"])
    op.create_index("ix_crm_webhook_processing", "crm_webhook_events", ["processing_status", "received_at"])
    op.create_index("ix_crm_webhook_correlation_id", "crm_webhook_events", ["correlation_id"])

    op.create_table(
        "integration_health_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="unknown"),
        sa.Column("checks_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("checked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connection_id"], ["crm_connections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_integration_health_tenant_id", "integration_health_snapshots", ["tenant_id"])
    op.create_index(
        "ix_integration_health_scope",
        "integration_health_snapshots",
        ["tenant_id", "connection_id", "checked_at"],
    )

    op.create_table(
        "integration_dead_letters",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("delivery_id", sa.Uuid()),
        sa.Column("status", sa.String(40), nullable=False, server_default="open"),
        sa.Column("reason_code", sa.String(80)),
        sa.Column("reason_message", sa.String(1000)),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["delivery_id"], ["crm_deliveries.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_integration_dead_letters_tenant_id", "integration_dead_letters", ["tenant_id"])
    op.create_index(
        "ix_integration_dead_letter_scope", "integration_dead_letters", ["tenant_id", "status", "created_at"]
    )

    op.create_table(
        "lead_activity_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(160), nullable=False),
        sa.Column("actor_type", sa.String(60), nullable=False, server_default="system"),
        sa.Column("actor_id", sa.String(160)),
        sa.Column("correlation_id", sa.String(128)),
        sa.Column("details_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lead_activity_tenant_id", "lead_activity_events", ["tenant_id"])
    op.create_index("ix_lead_activity_scope", "lead_activity_events", ["tenant_id", "lead_id", "occurred_at"])
    op.create_index("ix_lead_activity_correlation_id", "lead_activity_events", ["correlation_id"])

    # Backfill production extension rows without mutating existing lead IDs/API contracts.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "INSERT INTO lead_profiles (id, tenant_id, lead_id, public_id, normalized_email, normalized_phone, "
            "lifecycle_status, qualification_status, qualification_score, consent_status, custom_fields_json, created_at, updated_at) "
            "SELECT gen_random_uuid(), tenant_id, id, 'lead_' || replace(gen_random_uuid()::text, '-', ''), "
            "lower(email), regexp_replace(coalesce(phone, ''), '[^0-9+]', '', 'g'), "
            "CASE WHEN status IN ('new','contacted','qualified','converted','archived') THEN status ELSE 'new' END, "
            "CASE WHEN status='qualified' THEN 'qualified' ELSE 'pending' END, 0, "
            "CASE WHEN consent THEN 'granted' ELSE 'unknown' END, COALESCE(fields_json, '{}'::jsonb), created_at, updated_at "
            "FROM leads ON CONFLICT (tenant_id, lead_id) DO NOTHING"
        )
        for table in TENANT_TABLES:
            op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            op.execute(
                f'CREATE POLICY tenant_isolation ON "{table}" '
                "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
                "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
            )
            op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{table}" TO northstar_app')
    else:
        # SQLite test environments get deterministic extension rows through application services.
        pass


def downgrade() -> None:
    for table in reversed(TENANT_TABLES):
        op.drop_table(table)
