"""Durable domain-operation dispatch failure handling."""

from __future__ import annotations

from typing import Any

from fastapi import Request

from northstar_api.dependencies import DBSession
from northstar_api.models import Workspace, WorkspaceStatus
from northstar_api.modules.branding.repositories import persist_branding_document
from northstar_api.security import Principal

from northstar_api.modules.workspace.brand_cache import invalidate_brand_cache
from northstar_api.modules.workspace.contracts import DomainRecord, WorkspaceSettingsBundle
from northstar_api.modules.workspace.store import (
    record_workspace_change,
    save_document,
    settings_document,
)


async def mark_dispatch_failed(
    *,
    session: DBSession,
    principal: Principal,
    request: Request,
    workspace: Workspace,
    document: WorkspaceSettingsBundle,
    domain: DomainRecord,
    operation: str,
    persist: Any = None,
    record_change: Any = None,
    invalidate: Any = None,
) -> None:
    """Fence stale queue failures before recording a retryable domain error."""
    queued_status = "verifying" if operation == "verification" else "certificate_pending"
    domain_id = domain.id
    hostname = domain.hostname
    verification_name = domain.verification_name
    verification_value = domain.verification_value
    await session.refresh(
        workspace,
        attribute_names=["settings_json", "status"],
        with_for_update=True,
    )
    persist = persist or persist_branding_document
    record_change = record_change or record_workspace_change
    invalidate = invalidate or invalidate_brand_cache
    document = settings_document(workspace)
    current = next((item for item in document.domains.domains if item.id == domain_id), None)
    if (
        workspace.status != WorkspaceStatus.ACTIVE
        or current is None
        or current.hostname != hostname
        or current.status != queued_status
        or current.verification_name != verification_name
        or current.verification_value != verification_value
    ):
        await session.rollback()
        return
    current.status = "failed"
    current.failure_reason = "Background worker dispatch is unavailable; retry this operation"
    save_document(workspace, document)
    await persist(session, workspace, document)
    record_change(
        session,
        principal,
        workspace,
        f"workspace.domain.{operation}.dispatch_failed",
        ["status", "failureReason"],
        resource_type="workspace_custom_domain",
        resource_id=current.id,
        after={
            "hostname": current.hostname,
            "status": current.status,
            "failureReason": current.failure_reason,
        },
        reason="Worker dispatch failed after durable request state was committed",
        request=request,
    )
    await session.commit()
    await invalidate(workspace.id, hostnames=[current.hostname])


__all__ = ["mark_dispatch_failed"]
