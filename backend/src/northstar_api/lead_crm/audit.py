from __future__ import annotations

import re
from typing import Any, Literal
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.lead_crm.audit_models import IntegrationAuditEvent
from northstar_api.logging import request_id_ctx

AuditCategory = Literal[
    "security",
    "workspace",
    "access",
    "agent",
    "conversation",
    "education",
    "lead",
    "crm",
    "channel",
    "billing",
    "api",
    "integration",
    "system",
]
AuditSeverity = Literal["info", "warning", "critical"]
AuditOutcome = Literal["success", "denied", "failure"]

_SENSITIVE_KEYS = {
    "password",
    "passwordhash",
    "token",
    "accesstoken",
    "refreshtoken",
    "secret",
    "clientsecret",
    "credentials",
    "credentialsencrypted",
    "authorization",
    "cookie",
    "apikey",
    "apikeysecret",
    "mfasecret",
    "totpsecret",
    "codeverifier",
    "twostepverificationpin",
}
_SENSITIVE_SUFFIXES = (
    "password",
    "secret",
    "token",
    "authorization",
    "cookie",
    "apikey",
    "codeverifier",
)
_REDACTED = "[REDACTED]"


def _key_id(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _sensitive_key(value: object) -> bool:
    key = _key_id(value)
    return key in _SENSITIVE_KEYS or key.endswith(_SENSITIVE_SUFFIXES)


def redact_audit_payload(value: Any) -> Any:
    """Recursively redact secrets before durable storage and before API output."""
    if isinstance(value, dict):
        return {
            str(key): (_REDACTED if _sensitive_key(key) else redact_audit_payload(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_audit_payload(item) for item in value]
    if isinstance(value, tuple):
        return [redact_audit_payload(item) for item in value]
    return value


def _workspace_from_request(request: Request | None) -> UUID | None:
    if request is None:
        return None
    raw = request.headers.get("x-workspace-id", "").strip()
    if not raw:
        return None
    try:
        return UUID(raw)
    except ValueError:
        return None


def record_audit_event(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    actor_user_id: UUID | None,
    action: str,
    entity_type: str,
    entity_id: str,
    workspace_id: UUID | None = None,
    category: AuditCategory = "system",
    severity: AuditSeverity = "info",
    outcome: AuditOutcome = "success",
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    request: Request | None = None,
) -> None:
    resolved_workspace = workspace_id or _workspace_from_request(request)
    session.add(
        IntegrationAuditEvent(
            tenant_id=tenant_id,
            workspace_id=resolved_workspace,
            actor_user_id=actor_user_id,
            action=action[:160],
            entity_type=entity_type[:100],
            entity_id=entity_id[:160],
            category=category,
            severity=severity,
            outcome=outcome,
            before_json=redact_audit_payload(before or {}),
            after_json=redact_audit_payload(after or {}),
            metadata_json=redact_audit_payload(metadata or {}),
            request_id=request_id_ctx.get(),
            ip_address=request.client.host[:80] if request and request.client else None,
            user_agent=request.headers.get("user-agent", "")[:500] if request else None,
        )
    )


def record_integration_audit(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    actor_user_id: UUID | None,
    action: str,
    entity_type: str,
    entity_id: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    request: Request | None = None,
    workspace_id: UUID | None = None,
    category: AuditCategory = "integration",
    severity: AuditSeverity = "info",
    outcome: AuditOutcome = "success",
    metadata: dict[str, Any] | None = None,
) -> None:
    """Backward-compatible wrapper used by existing CRM/channel audit call sites."""
    record_audit_event(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        category=category,
        severity=severity,
        outcome=outcome,
        before=before,
        after=after,
        metadata=metadata,
        request=request,
    )
