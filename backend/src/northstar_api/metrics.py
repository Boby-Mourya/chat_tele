from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

HTTP_REQUESTS = Counter(
    "northstar_http_requests_total", "HTTP requests", labelnames=("method", "route", "status")
)
HTTP_DURATION = Histogram(
    "northstar_http_request_duration_seconds", "HTTP request duration", labelnames=("method", "route")
)
CHAT_REQUESTS = Counter("northstar_chat_requests_total", "Chat requests", labelnames=("result",))
CHAT_DURATION = Histogram("northstar_chat_duration_seconds", "Verified chat response duration")
RETRIEVAL_DURATION = Histogram("northstar_retrieval_duration_seconds", "Knowledge retrieval duration")
RETRIEVAL_EVIDENCE = Histogram("northstar_retrieval_evidence_count", "Selected evidence count")
MODEL_ERRORS = Counter("northstar_model_errors_total", "Model errors", labelnames=("kind",))
RATE_LIMITED = Counter("northstar_rate_limited_total", "Rate-limited requests", labelnames=("scope",))
OUTBOX_BACKLOG = Gauge("northstar_outbox_backlog", "Unpublished outbox events")
INGESTION_TASKS = Counter(
    "northstar_ingestion_tasks_total", "Ingestion task outcomes", labelnames=("result",)
)

CHANNEL_WEBHOOK_RECEIVED = Counter(
    "northstar_channel_webhook_received_total",
    "Verified channel webhook events accepted",
    labelnames=("provider",),
)
CHANNEL_WEBHOOK_REJECTED = Counter(
    "northstar_channel_webhook_rejected_total",
    "Channel webhook requests rejected",
    labelnames=("provider", "reason"),
)
LEAD_EVENTS = Counter(
    "northstar_lead_events_total",
    "Lead lifecycle events",
    labelnames=("event",),
)
CRM_DELIVERIES = Counter(
    "northstar_crm_delivery_total",
    "CRM delivery outcomes",
    labelnames=("provider", "result"),
)
CRM_DELIVERY_RETRIES = Counter(
    "northstar_crm_delivery_retry_total",
    "CRM delivery retries",
    labelnames=("provider", "reason"),
)
CRM_RATE_LIMITED = Counter(
    "northstar_crm_rate_limited_total",
    "CRM rate-limit responses",
    labelnames=("provider",),
)
CRM_DELIVERY_DURATION = Histogram(
    "northstar_crm_delivery_duration_seconds",
    "CRM provider request duration",
    labelnames=("provider", "operation"),
)
CRM_AUTH_REFRESH_FAILURES = Counter(
    "northstar_crm_auth_refresh_failure_total",
    "CRM credential refresh failures",
    labelnames=("provider",),
)
CRM_CONNECTION_HEALTH = Gauge(
    "northstar_crm_connection_health",
    "CRM connection health where 1 is healthy and 0 is not healthy",
    labelnames=("provider", "connection"),
)
CRM_QUEUE_DEPTH = Gauge(
    "northstar_crm_queue_depth",
    "CRM queued/retrying delivery count",
    labelnames=("provider",),
)
CRM_DLQ_DEPTH = Gauge(
    "northstar_crm_dlq_depth",
    "Open CRM dead-letter count",
    labelnames=("provider",),
)
CRM_WEBHOOK_RECEIVED = Counter(
    "northstar_crm_webhook_received_total",
    "Verified inbound CRM webhook events",
    labelnames=("provider",),
)
CRM_WEBHOOK_REJECTED = Counter(
    "northstar_crm_webhook_rejected_total",
    "Rejected inbound CRM webhook requests",
    labelnames=("provider", "reason"),
)
