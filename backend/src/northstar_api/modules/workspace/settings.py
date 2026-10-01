from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from northstar_api.access_policy import WORKSPACE_GRANTS, WORKSPACE_PERMISSIONS
from northstar_api.dependencies import DBSession, get_current_principal, require_permissions
from northstar_api.security import Principal

from .contracts import (
    DeveloperSettings,
    GeneralSettings,
    NotificationSettings,
    SecuritySettings,
    WorkspaceSettingsBundle,
)
from .repositories.workspace_write_lock import lock_workspace_settings
from .security_policy import normalize_trusted_domains, validate_business_timezone, validate_security_settings
from .services.settings_service import (
    sync_developer_settings_record,
    sync_notification_settings_record,
    sync_security_policy_record,
    update_developer_settings,
    update_general_settings,
    update_notification_settings,
    update_security_settings,
)
from .store import load_workspace, record_workspace_change, settings_document

router = APIRouter()
CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]
SettingsViewPrincipal = Annotated[Principal, Depends(require_permissions("settings.view"))]
SettingsManagePrincipal = Annotated[Principal, Depends(require_permissions("settings.manage"))]
RolesManagePrincipal = Annotated[Principal, Depends(require_permissions("roles.manage"))]


def _visible_bundle(document: WorkspaceSettingsBundle, principal: Principal) -> WorkspaceSettingsBundle:
    visible = WorkspaceSettingsBundle()
    permissions = set(principal.permissions)

    if permissions & {"settings.view", "settings.manage"}:
        visible.general = document.general
        visible.security = document.security
        visible.notifications = document.notifications
        visible.developer = document.developer

    if permissions & {"roles.manage", "teams.manage"}:
        visible.roles = document.roles
    if "teams.manage" in permissions:
        visible.teams = document.teams

    branding_permissions = {
        "branding.view",
        "branding.edit",
        "branding.publish",
        "branding.domain.manage",
    }
    if permissions & branding_permissions:
        visible.dashboard = document.dashboard
        visible.branding_draft = document.branding_draft
        visible.branding_published = document.branding_published
        visible.branding_versions = document.branding_versions
        visible.domains = document.domains

    return visible


@router.get("/", response_model=WorkspaceSettingsBundle)
async def get_settings(principal: CurrentPrincipal, session: DBSession) -> WorkspaceSettingsBundle:
    _, workspace = await load_workspace(principal, session)
    return _visible_bundle(settings_document(workspace), principal)


@router.get("/capabilities")
async def get_capabilities(principal: RolesManagePrincipal) -> dict[str, Any]:
    _ = principal
    return {
        "permissions": sorted(WORKSPACE_PERMISSIONS),
        "builtinRoles": {name: sorted(values) for name, values in WORKSPACE_GRANTS.items()},
        "resourceKinds": [
            "agents",
            "knowledge",
            "conversations",
            "courses",
            "batches",
            "students",
            "leads",
            "channels",
            "crm",
        ],
    }


@router.patch("/general", response_model=GeneralSettings)
async def update_general(
    payload: GeneralSettings,
    request: Request,
    principal: SettingsManagePrincipal,
    session: DBSession,
) -> GeneralSettings:
    _, workspace = await load_workspace(principal, session)
    validate_business_timezone(payload.business_hours.timezone)
    await lock_workspace_settings(session, workspace)
    before = update_general_settings(workspace, payload)
    record_workspace_change(
        session,
        principal,
        workspace,
        "workspace.settings.general.updated",
        sorted(payload.model_fields_set),
        resource_type="workspace_settings",
        resource_id=f"{workspace.id}:general",
        before=before,
        after=payload.model_dump(by_alias=True, mode="json"),
        request=request,
    )
    await session.commit()
    return payload


@router.patch("/security", response_model=SecuritySettings)
async def update_security(
    payload: SecuritySettings,
    request: Request,
    principal: SettingsManagePrincipal,
    session: DBSession,
) -> SecuritySettings:
    validate_security_settings(payload)
    payload = normalize_trusted_domains(payload)
    _, workspace = await load_workspace(principal, session)
    await lock_workspace_settings(session, workspace)
    before = update_security_settings(workspace, payload)
    await sync_security_policy_record(session, workspace, payload)
    record_workspace_change(
        session,
        principal,
        workspace,
        "workspace.settings.security.updated",
        sorted(payload.model_fields_set),
        resource_type="workspace_security_policy",
        resource_id=str(workspace.id),
        before=before,
        after=payload.model_dump(by_alias=True, mode="json"),
        request=request,
    )
    await session.commit()
    return payload


@router.patch("/notifications", response_model=NotificationSettings)
async def update_notifications(
    payload: NotificationSettings,
    request: Request,
    principal: SettingsManagePrincipal,
    session: DBSession,
) -> NotificationSettings:
    _, workspace = await load_workspace(principal, session)
    await lock_workspace_settings(session, workspace)
    before = update_notification_settings(workspace, payload)
    await sync_notification_settings_record(session, workspace, payload)
    record_workspace_change(
        session,
        principal,
        workspace,
        "workspace.settings.notifications.updated",
        sorted(payload.model_fields_set),
        resource_type="workspace_notification_settings",
        resource_id=str(workspace.id),
        before=before,
        after=payload.model_dump(by_alias=True, mode="json"),
        request=request,
    )
    await session.commit()
    return payload


@router.patch("/developer", response_model=DeveloperSettings)
async def update_developer(
    payload: DeveloperSettings,
    request: Request,
    principal: SettingsManagePrincipal,
    session: DBSession,
) -> DeveloperSettings:
    _, workspace = await load_workspace(principal, session)
    await lock_workspace_settings(session, workspace)
    before = update_developer_settings(workspace, payload)
    await sync_developer_settings_record(session, workspace, payload)
    record_workspace_change(
        session,
        principal,
        workspace,
        "workspace.settings.developer.updated",
        sorted(payload.model_fields_set),
        resource_type="workspace_developer_settings",
        resource_id=str(workspace.id),
        before=before,
        after=payload.model_dump(by_alias=True, mode="json"),
        request=request,
    )
    await session.commit()
    return payload
