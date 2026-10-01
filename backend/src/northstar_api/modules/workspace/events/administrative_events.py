from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.lead_crm.audit import record_audit_event
from northstar_api.services.outbox import enqueue_event

_EVENT_NAMES = {
    "workspace.settings.general.updated": "WorkspaceUpdated",
    "workspace.settings.security.updated": "WorkspaceSecurityUpdated",
    "workspace.settings.notifications.updated": "WorkspaceNotificationsUpdated",
    "workspace.settings.developer.updated": "WorkspaceDeveloperSettingsUpdated",
    "workspace.member.invited": "WorkspaceMemberInvited",
    "workspace.member.role.updated": "WorkspaceMemberRoleChanged",
    "workspace.member.suspended": "WorkspaceMemberSuspended",
    "workspace.member.reactivated": "WorkspaceMemberReactivated",
    "workspace.role.updated": "WorkspaceRoleUpdated",
    "workspace.teams.updated": "WorkspaceTeamsUpdated",
    "workspace.brand.draft.updated": "BrandUpdated",
    "workspace.brand.published": "BrandPublished",
    "workspace.brand.rollback": "BrandRolledBack",
    "workspace.domain.created": "CustomDomainCreated",
    "workspace.domain.verified": "CustomDomainVerified",
    "workspace.domain.activated": "CustomDomainActivated",
    "workspace.domain.disabled": "CustomDomainDisabled",
    "workspace.api_key.created": "WorkspaceApiKeyCreated",
    "workspace.api_key.revoked": "WorkspaceApiKeyRevoked",
}


def domain_event_name(action: str) -> str:
    return _EVENT_NAMES.get(action, "WorkspaceAdministrativeChanged")


def emit_workspace_administrative_event(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    actor_user_id: UUID | None,
    action: str,
    resource_type: str = "workspace",
    resource_id: str | None = None,
    fields: list[str] | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
    request: Request | None = None,
) -> None:
    metadata: dict[str, Any] = {
        "fields": fields or [],
        "domainEvent": domain_event_name(action),
    }
    if reason:
        metadata["reason"] = reason
    resolved_resource_id = resource_id or str(workspace_id)
    record_audit_event(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        action=action,
        entity_type=resource_type,
        entity_id=resolved_resource_id,
        category="workspace",
        before=before,
        after=after,
        metadata=metadata,
        request=request,
    )
    enqueue_event(
        session,
        tenant_id=tenant_id,
        aggregate_type=resource_type,
        aggregate_id=resolved_resource_id,
        event_type=f"workspace.{domain_event_name(action)}.v1",
        payload={
            "tenantId": str(tenant_id),
            "workspaceId": str(workspace_id),
            "resourceType": resource_type,
            "resourceId": resolved_resource_id,
            "action": action,
            "fields": fields or [],
            **({"reason": reason} if reason else {}),
        },
    )


__all__ = ["domain_event_name", "emit_workspace_administrative_event"]
