from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class CRMDeliveryAttemptOut(BaseModel):
    """Safe operational view of one CRM delivery attempt.

    Attempt metadata is intentionally excluded because provider adapters may store
    implementation details there that should not be exposed through the product UI.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    delivery_id: UUID
    attempt_number: int
    started_at: datetime
    finished_at: datetime | None
    http_status: int | None
    latency_ms: int | None
    result_status: str | None
    normalized_error_code: str | None
    provider_error_code: str | None
    provider_request_id: str | None
