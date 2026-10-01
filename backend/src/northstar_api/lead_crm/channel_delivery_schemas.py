from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ChannelOutboundDeliveryOut(BaseModel):
    """Safe Workspace-facing provider-neutral outbound delivery evidence."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    connection_id: UUID | None
    connection_name: str | None
    message_id: UUID
    provider: str
    status: str
    error_code: str | None
    attempt_count: int
    dispatch_attempts: int
    dispatched_at: datetime | None
    processed_at: datetime | None
    next_dispatch_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ChannelDeliveryAttemptOut(BaseModel):
    """Safe Workspace-facing evidence for one channel delivery attempt."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    delivery_id: UUID
    phase: str
    attempt_number: int
    outcome: str
    error_code: str | None
    created_at: datetime
