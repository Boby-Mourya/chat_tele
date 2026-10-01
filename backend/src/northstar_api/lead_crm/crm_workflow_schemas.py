from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from northstar_api.schemas import APIModel

CRMWorkflowStageStatus = Literal["ready", "warning", "blocked"]
CRMWorkflowJourneyStage = Literal[
    "local_lead",
    "awaiting_routing",
    "in_progress",
    "provider_acknowledged",
    "verifying",
    "verified",
    "attention_required",
    "dead_letter",
]


class CRMWorkflowReadinessStageOut(APIModel):
    id: str
    label: str
    description: str
    status: CRMWorkflowStageStatus
    detail: str
    action_label: str | None = None
    action_path: str | None = None


class CRMWorkflowReadinessOut(APIModel):
    ready: bool
    stages: list[CRMWorkflowReadinessStageOut]


class CRMWorkflowCountsOut(APIModel):
    resolved_conversations: int
    local_leads: int
    leads_without_delivery: int
    total_deliveries: int
    in_flight_deliveries: int
    verified_deliveries: int
    attention_deliveries: int
    open_dead_letters: int
    by_status: dict[str, int]


class CRMWorkflowConnectionOut(APIModel):
    id: UUID
    name: str
    provider: str
    environment: str
    status: str
    credentials_configured: bool
    mapping_configured: bool
    mapping_status: str | None
    mapping_version: int | None
    enabled_route_count: int
    auto_sync_new_leads: bool
    auto_sync_updates: bool
    ready: bool
    last_health_at: datetime | None
    last_success_at: datetime | None
    last_failure_at: datetime | None
    last_error: str | None


class CRMWorkflowDeliveryOut(APIModel):
    id: UUID
    connection_id: UUID
    connection_name: str
    provider: str
    operation: str
    status: str
    verification_status: str
    external_record_id: str | None
    attempt_count: int
    verification_attempt_count: int
    acknowledged_at: datetime | None
    verified_at: datetime | None
    next_retry_at: datetime | None
    next_verification_at: datetime | None
    last_error_code: str | None
    last_error_message: str | None
    verification_error_code: str | None
    verification_error_message: str | None
    dead_letter_open: bool
    created_at: datetime
    updated_at: datetime


class CRMWorkflowJourneyOut(APIModel):
    lead_id: UUID
    conversation_id: UUID | None
    conversation_public_id: str | None
    agent_id: UUID
    agent_name: str
    customer_name: str | None
    email: str | None
    phone: str | None
    source_channel: str | None
    lifecycle_status: str
    qualification_status: str | None
    qualification_score: int | None
    stage: CRMWorkflowJourneyStage
    stage_label: str
    stage_detail: str
    next_action_label: str | None
    next_action_path: str | None
    delivery: CRMWorkflowDeliveryOut | None
    created_at: datetime
    updated_at: datetime


class CRMWorkflowOut(APIModel):
    generated_at: datetime
    workspace_id: UUID
    readiness: CRMWorkflowReadinessOut
    counts: CRMWorkflowCountsOut
    connections: list[CRMWorkflowConnectionOut]
    recent_journeys: list[CRMWorkflowJourneyOut]
