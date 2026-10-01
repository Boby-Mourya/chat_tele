from __future__ import annotations

from typing import Any

from fastapi import Request

from northstar_api.dependencies import DBSession
from northstar_api.models import Workspace
from northstar_api.security import Principal
from northstar_api.workspace_contract import WhiteLabelWrite

from .contracts import ExtendedBranding, WorkspaceSettingsBundle
from .events.administrative_events import emit_workspace_administrative_event


async def load_workspace(principal: Principal, session: DBSession) -> tuple[Any, Workspace]:
    # The legacy router package also registers the canonical Workspace API.
    # Import its existing scoped loader at request time rather than during
    # module initialization, so either import order avoids a router cycle.
    from northstar_api.routers.workspace import _load_workspace

    tenant, workspace, _, _ = await _load_workspace(
        principal.tenant_id,
        principal.workspace_id,
        principal.user_id,
        session,
    )
    return tenant, workspace


def settings_document(workspace: Workspace) -> WorkspaceSettingsBundle:
    raw = dict(workspace.settings_json or {}).get("workspaceSettingsV2", {})
    try:
        document = WorkspaceSettingsBundle.model_validate(raw)
    except (TypeError, ValueError):
        document = WorkspaceSettingsBundle()

    legacy_security = dict(workspace.settings_json or {}).get("security", {})
    if legacy_security:
        document.security.sensitive_data_masking = bool(
            legacy_security.get("sensitiveDataMasking", document.security.sensitive_data_masking)
        )
        document.security.security_contact = legacy_security.get(
            "securityContact", document.security.security_contact
        )

    if workspace.branding_json and document.branding_published is None:
        legacy = {
            key: value
            for key, value in workspace.branding_json.items()
            if key not in {"customDomain", "dnsStatus"}
        }
        try:
            identity = WhiteLabelWrite.model_validate(legacy)
        except (TypeError, ValueError):
            identity = None
        if identity is not None:
            document.branding_published = ExtendedBranding(identity=identity)
            document.branding_draft = document.branding_published.model_copy(deep=True)
    return document


def save_document(workspace: Workspace, document: WorkspaceSettingsBundle) -> None:
    settings = dict(workspace.settings_json or {})
    settings["workspaceSettingsV2"] = document.model_dump(by_alias=True, mode="json")
    workspace.settings_json = settings


def record_workspace_change(
    session: DBSession,
    principal: Principal,
    workspace: Workspace,
    action: str,
    fields: list[str] | None = None,
    *,
    resource_type: str = "workspace",
    resource_id: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
    request: Request | None = None,
) -> None:
    emit_workspace_administrative_event(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=workspace.id,
        actor_user_id=principal.user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        fields=fields,
        before=before,
        after=after,
        reason=reason,
        request=request,
    )
