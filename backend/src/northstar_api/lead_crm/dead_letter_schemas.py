from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class CRMDeadLetterOut(BaseModel):
    """Safe workspace-facing view of one persisted CRM dead letter."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    delivery_id: UUID
    lead_id: UUID
    connection_id: UUID
    provider: str
    status: str
    reason_code: str | None
    reason_message: str | None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None


class CRMDeadLetterReplayOut(BaseModel):
    """Result of safely queueing the existing delivery retry for one dead letter."""

    model_config = ConfigDict(extra="forbid")

    dead_letter_id: UUID
    delivery_id: UUID
    dead_letter_status: str
    delivery_status: str
    replayed_at: datetime
