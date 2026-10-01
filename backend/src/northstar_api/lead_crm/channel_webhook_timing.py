from __future__ import annotations

from typing import Any

from sqlalchemy import String, cast, func, select

from northstar_api.lead_crm.models import RawWebhookEvent
from northstar_api.models import OutboxEvent

CHANNEL_RECEIVED_EVENT_TYPE = "channel.event.received.v1"


def channel_webhook_pending_since_expression() -> Any:
    """Return the latest queue/requeue time, falling back to immutable receipt time."""

    latest_enqueue_at = (
        select(func.max(OutboxEvent.occurred_at))
        .where(
            OutboxEvent.tenant_id == RawWebhookEvent.tenant_id,
            OutboxEvent.aggregate_type == "raw_webhook_event",
            func.replace(OutboxEvent.aggregate_id, "-", "")
            == func.replace(cast(RawWebhookEvent.id, String), "-", ""),
            OutboxEvent.event_type == CHANNEL_RECEIVED_EVENT_TYPE,
        )
        .correlate(RawWebhookEvent)
        .scalar_subquery()
    )
    return func.coalesce(latest_enqueue_at, RawWebhookEvent.received_at)
