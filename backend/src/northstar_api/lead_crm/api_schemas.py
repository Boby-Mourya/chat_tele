from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from northstar_api.lead_crm.domain import CRMDeliveryStatus, CRMProvider
from northstar_api.lead_crm.generic_contract import configured_capabilities, validate_configuration


class LeadCRMModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QualifyLeadRequest(LeadCRMModel):
    score: int = Field(default=100, ge=0, le=100)
    reason: str = Field(min_length=1, max_length=1000)


class SyncLeadRequest(LeadCRMModel):
    reason: str = Field(default="manual", min_length=1, max_length=240)


class CRMConnectionCreate(LeadCRMModel):
    provider: CRMProvider
    name: str = Field(min_length=2, max_length=160)
    environment: Literal["production", "sandbox", "development"] = "production"
    region: str | None = Field(default=None, max_length=80)
    configuration: dict[str, Any] = Field(default_factory=dict)
    credentials: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_generic_contract(self) -> Self:
        # Empty drafts remain legal, but credentialed/configured connections must
        # pass the same contract used before every outbound runtime request.
        if self.provider == CRMProvider.GENERIC_REST and (self.configuration or self.credentials):
            validate_configuration(self.configuration)
        return self


class CRMConnectionOut(LeadCRMModel):
    id: UUID
    public_id: str
    provider: str
    name: str
    environment: str
    region: str | None
    status: str
    configuration: dict[str, Any]
    capabilities: dict[str, Any]
    last_authenticated_at: datetime | None
    last_health_at: datetime | None
    last_success_at: datetime | None
    last_failure_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def expose_configured_capabilities(self) -> Self:
        # Recompute for historical rows too: stale class-level flags in the DB
        # must not advertise operations missing from the actual configuration.
        if self.provider == CRMProvider.GENERIC_REST.value:
            self.capabilities = configured_capabilities(self.configuration)
        return self


class CRMWorkspaceSettingsPatch(LeadCRMModel):
    auto_sync_new_leads: bool | None = None
    auto_sync_updates: bool | None = None


class CRMWorkspaceSettingsOut(LeadCRMModel):
    connection_id: UUID
    auto_sync_new_leads: bool
    auto_sync_updates: bool
    updated_at: datetime


class CRMRouteCreate(LeadCRMModel):
    name: str = Field(min_length=2, max_length=160)
    enabled: bool = True
    priority: int = Field(default=100, ge=0, le=10000)
    conditions: dict[str, Any] = Field(default_factory=dict)
    connection_ids: list[UUID] = Field(default_factory=list)


class CRMRouteOut(LeadCRMModel):
    id: UUID
    name: str
    enabled: bool
    priority: int
    version: int
    conditions: dict[str, Any]
    connection_ids: list[str]
    created_at: datetime
    updated_at: datetime


class CRMMappingPut(LeadCRMModel):
    object_name: str = Field(default="Leads", min_length=1, max_length=120)
    mapping: dict[str, Any]


class CRMMappingOut(LeadCRMModel):
    connection_id: UUID
    object_name: str
    version: int
    status: str
    mapping: dict[str, Any]
    validation: dict[str, Any]
    schema_hash: str | None


class CRMDeliveryOut(LeadCRMModel):
    id: UUID
    lead_id: UUID
    connection_id: UUID
    provider: str
    operation: str
    status: CRMDeliveryStatus
    attempt_count: int
    verification_status: str
    verification_attempt_count: int
    next_verification_at: datetime | None
    verification_error_code: str | None
    verification_error_message: str | None
    verification_evidence: dict[str, Any]
    external_record_id: str | None
    queued_at: datetime | None
    sent_at: datetime | None
    acknowledged_at: datetime | None
    verified_at: datetime | None
    next_retry_at: datetime | None
    last_error_code: str | None
    last_error_message: str | None
    provider_http_status: int | None
    provider_code: str | None
    provider_request_id: str | None
    created_at: datetime
    updated_at: datetime


class LeadActivityOut(LeadCRMModel):
    id: UUID
    event_type: str
    actor_type: str
    actor_id: str | None
    correlation_id: str | None
    details: dict[str, Any]
    occurred_at: datetime
