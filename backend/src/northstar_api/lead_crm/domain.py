from __future__ import annotations

import enum


class LeadLifecycleStatus(str, enum.Enum):
    NEW = "new"
    IDENTIFIED = "identified"
    ENGAGED = "engaged"
    QUALIFIED = "qualified"
    UNQUALIFIED = "unqualified"
    CONTACTED = "contacted"
    CONVERTED = "converted"
    LOST = "lost"
    ARCHIVED = "archived"


class QualificationStatus(str, enum.Enum):
    PENDING = "pending"
    QUALIFIED = "qualified"
    UNQUALIFIED = "unqualified"
    MANUAL_REVIEW = "manual_review"


class IdentityType(str, enum.Enum):
    EMAIL = "email"
    PHONE = "phone"
    WHATSAPP = "whatsapp"
    INSTAGRAM = "instagram"
    FACEBOOK = "facebook"
    TELEGRAM = "telegram"
    WIDGET_VISITOR = "widget_visitor"
    API_EXTERNAL_ID = "api_external_id"
    CUSTOM = "custom"


class ChannelProvider(str, enum.Enum):
    WHATSAPP = "whatsapp"
    INSTAGRAM = "instagram"
    FACEBOOK_MESSENGER = "facebook_messenger"
    TELEGRAM = "telegram"
    WIDGET = "widget"
    API = "api"
    SLACK = "slack"
    CUSTOM = "custom"


class CRMProvider(str, enum.Enum):
    ZOHO = "zoho"
    SALESFORCE = "salesforce"
    HUBSPOT = "hubspot"
    DYNAMICS365 = "dynamics365"
    PIPEDRIVE = "pipedrive"
    FRESHSALES = "freshsales"
    GENERIC_REST = "generic_rest"
    GENERIC_WEBHOOK = "generic_webhook"


class CRMConnectionStatus(str, enum.Enum):
    DRAFT = "draft"
    CONNECTING = "connecting"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    AUTH_REQUIRED = "auth_required"
    RATE_LIMITED = "rate_limited"
    CONFIGURATION_ERROR = "configuration_error"
    DISABLED = "disabled"


class CRMDeliveryStatus(str, enum.Enum):
    CREATED = "created"
    ROUTED = "routed"
    QUEUED = "queued"
    PROCESSING = "processing"
    SENT = "sent"
    ACKNOWLEDGED = "acknowledged"
    VERIFYING = "verifying"
    VERIFIED = "verified"
    RETRYING = "retrying"
    RATE_LIMITED = "rate_limited"
    AUTH_REQUIRED = "auth_required"
    MAPPING_ERROR = "mapping_error"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"
    CANCELLED = "cancelled"


class CRMOperation(str, enum.Enum):
    CREATE = "create"
    UPDATE = "update"
    UPSERT = "upsert"


class IntegrationHealthStatus(str, enum.Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    AUTH_REQUIRED = "auth_required"
    RATE_LIMITED = "rate_limited"
    CONFIGURATION_ERROR = "configuration_error"
    UNKNOWN = "unknown"


class NormalizedCRMErrorCode(str, enum.Enum):
    AUTHENTICATION_ERROR = "authentication_error"
    AUTHORIZATION_ERROR = "authorization_error"
    VALIDATION_ERROR = "validation_error"
    MAPPING_ERROR = "mapping_error"
    DUPLICATE_ERROR = "duplicate_error"
    RATE_LIMIT_ERROR = "rate_limit_error"
    TIMEOUT = "timeout"
    NETWORK_ERROR = "network_error"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    CONFIGURATION_ERROR = "configuration_error"
    UNKNOWN_ERROR = "unknown_error"


_ALLOWED_DELIVERY_TRANSITIONS: dict[CRMDeliveryStatus, frozenset[CRMDeliveryStatus]] = {
    CRMDeliveryStatus.CREATED: frozenset({CRMDeliveryStatus.ROUTED, CRMDeliveryStatus.CANCELLED}),
    CRMDeliveryStatus.ROUTED: frozenset({CRMDeliveryStatus.QUEUED, CRMDeliveryStatus.CANCELLED}),
    CRMDeliveryStatus.QUEUED: frozenset({CRMDeliveryStatus.PROCESSING, CRMDeliveryStatus.CANCELLED}),
    CRMDeliveryStatus.PROCESSING: frozenset(
        {
            CRMDeliveryStatus.SENT,
            CRMDeliveryStatus.ACKNOWLEDGED,
            CRMDeliveryStatus.RETRYING,
            CRMDeliveryStatus.RATE_LIMITED,
            CRMDeliveryStatus.AUTH_REQUIRED,
            CRMDeliveryStatus.MAPPING_ERROR,
            CRMDeliveryStatus.FAILED,
        }
    ),
    CRMDeliveryStatus.SENT: frozenset(
        {CRMDeliveryStatus.ACKNOWLEDGED, CRMDeliveryStatus.RETRYING, CRMDeliveryStatus.FAILED}
    ),
    CRMDeliveryStatus.ACKNOWLEDGED: frozenset({CRMDeliveryStatus.VERIFYING}),
    CRMDeliveryStatus.VERIFYING: frozenset({CRMDeliveryStatus.VERIFIED, CRMDeliveryStatus.ACKNOWLEDGED}),
    CRMDeliveryStatus.RETRYING: frozenset(
        {
            CRMDeliveryStatus.QUEUED,
            CRMDeliveryStatus.PROCESSING,
            CRMDeliveryStatus.DEAD_LETTER,
            CRMDeliveryStatus.CANCELLED,
        }
    ),
    CRMDeliveryStatus.RATE_LIMITED: frozenset(
        {CRMDeliveryStatus.RETRYING, CRMDeliveryStatus.DEAD_LETTER, CRMDeliveryStatus.CANCELLED}
    ),
    CRMDeliveryStatus.AUTH_REQUIRED: frozenset(
        {CRMDeliveryStatus.RETRYING, CRMDeliveryStatus.DEAD_LETTER, CRMDeliveryStatus.CANCELLED}
    ),
    CRMDeliveryStatus.MAPPING_ERROR: frozenset(
        {CRMDeliveryStatus.RETRYING, CRMDeliveryStatus.DEAD_LETTER, CRMDeliveryStatus.CANCELLED}
    ),
    CRMDeliveryStatus.FAILED: frozenset(
        {CRMDeliveryStatus.RETRYING, CRMDeliveryStatus.DEAD_LETTER, CRMDeliveryStatus.CANCELLED}
    ),
    CRMDeliveryStatus.VERIFIED: frozenset(),
    CRMDeliveryStatus.DEAD_LETTER: frozenset({CRMDeliveryStatus.RETRYING, CRMDeliveryStatus.CANCELLED}),
    CRMDeliveryStatus.CANCELLED: frozenset(),
}


def validate_delivery_transition(current: CRMDeliveryStatus, target: CRMDeliveryStatus) -> None:
    if target == current:
        return
    if target not in _ALLOWED_DELIVERY_TRANSITIONS[current]:
        raise ValueError(f"Invalid CRM delivery transition: {current.value} -> {target.value}")
