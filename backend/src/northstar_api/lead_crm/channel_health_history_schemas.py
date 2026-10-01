from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ChannelHealthSnapshotOut(BaseModel):
    """Safe Workspace-facing view of one scheduled channel health check."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    connection_id: UUID
    status: str
    error_code: str | None
    checked_at: datetime
