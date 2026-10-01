from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ChannelWebhookEventOut(BaseModel):
    """Safe Workspace-facing operational metadata for one inbound channel webhook event."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    connection_id: UUID
    provider: str
    event_type: str
    verification_status: str
    processing_status: str
    attempt_count: int
    error_code: str | None
    can_requeue: bool
    correlation_id: str
    received_at: datetime
    processed_at: datetime | None
