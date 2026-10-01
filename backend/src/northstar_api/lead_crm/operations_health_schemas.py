from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class CRMOperationalConnectionHealthOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection_id: UUID
    name: str
    provider: str
    status: str
    last_health_at: datetime | None
    last_success_at: datetime | None
    last_failure_at: datetime | None
    last_error: str | None
    pending_deliveries: int
    retrying_deliveries: int
    failed_deliveries: int
    open_dead_letters: int


class CRMOperationalHealthOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overall_status: str
    connection_count: int
    healthy_connections: int
    attention_connections: int
    pending_deliveries: int
    retrying_deliveries: int
    failed_deliveries: int
    open_dead_letters: int
    connections: list[CRMOperationalConnectionHealthOut]
