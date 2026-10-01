from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class CRMHealthSnapshotOut(BaseModel):
    """Safe Workspace-facing history for one CRM connection health check."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    connection_id: UUID
    status: str
    checks: dict[str, str]
    latency_ms: int | None
    checked_at: datetime
