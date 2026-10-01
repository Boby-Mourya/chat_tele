from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.models import Workspace
from northstar_api.modules.workspace.contracts import BrandVersion, WorkspaceSettingsBundle

from ..models import (
    WorkspaceBrand,
    WorkspaceBrandAsset,
    WorkspaceBrandSurface,
    WorkspaceBrandTheme,
    WorkspaceBrandVersion,
    WorkspaceCustomDomain,
    WorkspaceDashboardLayout,
    WorkspaceEmailBrand,
    WorkspaceWidgetBrand,
)


async def _workspace_row(session: AsyncSession, model: type[Any], workspace: Workspace) -> Any:
    value = await session.get(model, workspace.id)
    if value is None:
        value = model(workspace_id=workspace.id, tenant_id=workspace.tenant_id)
        session.add(value)
    return value


async def persist_branding_document(
    session: AsyncSession,
    workspace: Workspace,
    document: WorkspaceSettingsBundle,
    *,
    published_version: BrandVersion | None = None,
) -> None:
    """Dual-write normalized white-label records while compatibility JSON remains active."""
    draft = document.branding_draft
    published = document.branding_published

    brand = await _workspace_row(session, WorkspaceBrand, workspace)
    brand.draft_json = draft.model_dump(by_alias=True, mode="json")
    brand.published_json = published.model_dump(by_alias=True, mode="json") if published else None
    brand.published_version = max((item.version for item in document.branding_versions), default=0)

    theme = await _workspace_row(session, WorkspaceBrandTheme, workspace)
    theme.tokens_json = {
        "primary": draft.identity.primary_color,
        "secondary": draft.identity.secondary_color,
        **draft.colors.model_dump(by_alias=True, mode="json"),
    }
    theme.typography_json = draft.typography.model_dump(by_alias=True, mode="json")
    theme.appearance_json = draft.appearance.model_dump(by_alias=True, mode="json")

    dashboard = await _workspace_row(session, WorkspaceDashboardLayout, workspace)
    dashboard.config_json = draft.dashboard.model_dump(by_alias=True, mode="json")
    email = await _workspace_row(session, WorkspaceEmailBrand, workspace)
    email.config_json = draft.email.model_dump(by_alias=True, mode="json")
    widget = await _workspace_row(session, WorkspaceWidgetBrand, workspace)
    widget.config_json = draft.widget.model_dump(by_alias=True, mode="json")

    surfaces = {
        "authentication": draft.authentication.model_dump(by_alias=True, mode="json"),
        "navigation": draft.navigation,
        "identity": draft.identity.model_dump(by_alias=True, mode="json"),
    }
    for surface, config in surfaces.items():
        row = await session.scalar(
            select(WorkspaceBrandSurface).where(
                WorkspaceBrandSurface.tenant_id == workspace.tenant_id,
                WorkspaceBrandSurface.workspace_id == workspace.id,
                WorkspaceBrandSurface.surface == surface,
            )
        )
        if row is None:
            row = WorkspaceBrandSurface(
                tenant_id=workspace.tenant_id,
                workspace_id=workspace.id,
                surface=surface,
            )
            session.add(row)
        row.config_json = config

    assets = {
        "logo": draft.identity.logo_data_url,
        "favicon": draft.identity.favicon_data_url,
        "app_icon": draft.identity.app_icon_data_url,
        **draft.assets.model_dump(mode="json"),
    }
    for kind, value in assets.items():
        row = await session.scalar(
            select(WorkspaceBrandAsset).where(
                WorkspaceBrandAsset.tenant_id == workspace.tenant_id,
                WorkspaceBrandAsset.workspace_id == workspace.id,
                WorkspaceBrandAsset.kind == kind,
            )
        )
        if row is None:
            row = WorkspaceBrandAsset(
                tenant_id=workspace.tenant_id,
                workspace_id=workspace.id,
                kind=kind,
            )
            session.add(row)
        row.value = str(value or "")

    existing_domains = {
        row.id: row
        for row in await session.scalars(
            select(WorkspaceCustomDomain).where(
                WorkspaceCustomDomain.tenant_id == workspace.tenant_id,
                WorkspaceCustomDomain.workspace_id == workspace.id,
            )
        )
    }
    for domain in document.domains.domains:
        try:
            domain_id = UUID(domain.id)
        except ValueError:
            continue
        row = existing_domains.get(domain_id)
        if row is None:
            row = WorkspaceCustomDomain(
                id=domain_id,
                tenant_id=workspace.tenant_id,
                workspace_id=workspace.id,
                hostname=domain.hostname,
                verification_name=domain.verification_name,
                verification_value=domain.verification_value,
            )
            session.add(row)
        row.hostname = domain.hostname
        row.status = domain.status
        row.verification_name = domain.verification_name
        row.verification_value = domain.verification_value
        row.failure_reason = domain.failure_reason

    if published_version is not None:
        existing = await session.scalar(
            select(WorkspaceBrandVersion.id).where(
                WorkspaceBrandVersion.tenant_id == workspace.tenant_id,
                WorkspaceBrandVersion.workspace_id == workspace.id,
                WorkspaceBrandVersion.version == published_version.version,
            )
        )
        if existing is None:
            try:
                created_by = UUID(published_version.created_by)
            except ValueError:
                created_by = None
            session.add(
                WorkspaceBrandVersion(
                    tenant_id=workspace.tenant_id,
                    workspace_id=workspace.id,
                    version=published_version.version,
                    branding_json=published_version.branding.model_dump(by_alias=True, mode="json"),
                    created_by=created_by,
                    published_at=published_version.published_at,
                    change_note=published_version.change_note,
                )
            )

    await session.flush()


__all__ = ["persist_branding_document"]
