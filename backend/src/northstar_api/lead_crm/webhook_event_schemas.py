from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class CRMWebhookEventOut(BaseModel):
    """Safe Workspace-facing operational view of one inbound CRM webhook event."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    connection_id: UUID
    provider: str
    event_type: str
    verification_status: str
    processing_status: str
    correlation_id: str
    received_at: datetime
    processed_at: datetime | None
    last_error: str | None
