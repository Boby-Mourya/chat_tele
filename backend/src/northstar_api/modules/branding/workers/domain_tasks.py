from __future__ import annotations

import asyncio
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from northstar_api.config import get_settings
from northstar_api.database import build_engine, set_tenant_context, tenant_context
from northstar_api.models import Workspace, WorkspaceStatus
from northstar_api.modules.branding.repositories import persist_branding_document
from northstar_api.modules.branding.services.domain_service import (
    TLS_ELIGIBLE_DOMAIN_STATUSES,
    check_domain_tls,
    verify_domain_txt,
)
from northstar_api.modules.workspace.brand_cache import invalidate_brand_cache
from northstar_api.modules.workspace.contracts import DomainRecord, WorkspaceSettingsBundle
from northstar_api.modules.workspace.events.administrative_events import emit_workspace_administrative_event
from northstar_api.modules.workspace.store import save_document, settings_document
from northstar_api.workers.celery_app import celery_app

_DNS_ELIGIBLE_DOMAIN_STATUSES = frozenset({"verifying", "dns_pending", "pending"})


async def _load_workspace_and_domain(
    session: AsyncSession,
    tenant_id: UUID,
    workspace_id: UUID,
    domain_id: str,
) -> tuple[Workspace | None, WorkspaceSettingsBundle | None, DomainRecord | None]:
    workspace = await session.scalar(
        select(Workspace).where(
            Workspace.id == workspace_id,
            Workspace.tenant_id == tenant_id,
            Workspace.status == WorkspaceStatus.ACTIVE,
        )
    )
    if workspace is None:
        return None, None, None
    document = settings_document(workspace)
    domain = next((item for item in document.domains.domains if item.id == domain_id), None)
    return workspace, document, domain


async def _refresh_domain_for_result(
    session: AsyncSession,
    workspace: Workspace,
    domain_id: str,
    *,
    hostname: str,
    allowed_statuses: frozenset[str],
    verification_name: str | None = None,
    verification_value: str | None = None,
) -> tuple[WorkspaceSettingsBundle, DomainRecord] | None:
    """Lock and reload durable state after external I/O, before writing a worker result.

    An administrator may disable a domain or start a new verification while a
    queued worker is doing DNS/HTTPS I/O. Refreshing the workspace JSON under a
    row lock prevents a stale worker result from undoing that newer change.
    The lock is acquired *after* network I/O so the request isn't blocked on it.
    """
    await session.refresh(
        workspace,
        attribute_names=["settings_json", "status"],
        with_for_update=True,
    )
    if workspace.status != WorkspaceStatus.ACTIVE:
        return None
    document = settings_document(workspace)
    domain = next((item for item in document.domains.domains if item.id == domain_id), None)
    if domain is None or domain.hostname != hostname or domain.status not in allowed_statuses:
        return None
    if verification_name is not None and domain.verification_name != verification_name:
        return None
    if verification_value is not None and domain.verification_value != verification_value:
        return None
    return document, domain


async def _run_dns_verification(tenant_id: str, workspace_id: str, domain_id: str) -> None:
    tenant_uuid = UUID(tenant_id)
    workspace_uuid = UUID(workspace_id)
    settings = get_settings()
    engine = build_engine(
        settings,
        apply_runtime_role=(
            settings.is_postgres
            and settings.database_apply_runtime_role
            and not settings.app_auto_create_schema
        ),
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    token = tenant_context.set(str(tenant_uuid))
    hostname = ""
    try:
        async with factory() as session:
            await set_tenant_context(session, tenant_uuid)
            workspace, document, domain = await _load_workspace_and_domain(
                session,
                tenant_uuid,
                workspace_uuid,
                domain_id,
            )
            if workspace is None or document is None or domain is None:
                return
            hostname = domain.hostname
            if domain.status not in _DNS_ELIGIBLE_DOMAIN_STATUSES:
                return
            verification_name = domain.verification_name
            verification_value = domain.verification_value
            verified = await verify_domain_txt(domain)
            current = await _refresh_domain_for_result(
                session,
                workspace,
                domain_id,
                hostname=hostname,
                allowed_statuses=_DNS_ELIGIBLE_DOMAIN_STATUSES,
                verification_name=verification_name,
                verification_value=verification_value,
            )
            if current is None:
                return
            document, domain = current
            if verified:
                domain.status = "verified"
                domain.failure_reason = ""
                action = "workspace.domain.verified"
            else:
                domain.status = "dns_pending"
                domain.failure_reason = (
                    f"TXT record {domain.verification_name} does not yet match the verification token"
                )
                action = "workspace.domain.verification.pending"
            save_document(workspace, document)
            await persist_branding_document(session, workspace, document)
            emit_workspace_administrative_event(
                session,
                tenant_id=tenant_uuid,
                workspace_id=workspace_uuid,
                actor_user_id=None,
                action=action,
                resource_type="workspace_custom_domain",
                resource_id=domain.id,
                fields=["status", "failureReason"],
                after={"hostname": hostname, "status": domain.status},
                reason="Asynchronous DNS ownership verification",
            )
            await session.commit()
    finally:
        if hostname:
            await invalidate_brand_cache(workspace_uuid, hostnames=[hostname])
        tenant_context.reset(token)
        await engine.dispose()


async def _run_tls_check(tenant_id: str, workspace_id: str, domain_id: str) -> None:
    tenant_uuid = UUID(tenant_id)
    workspace_uuid = UUID(workspace_id)
    settings = get_settings()
    engine = build_engine(
        settings,
        apply_runtime_role=(
            settings.is_postgres
            and settings.database_apply_runtime_role
            and not settings.app_auto_create_schema
        ),
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    token = tenant_context.set(str(tenant_uuid))
    hostname = ""
    try:
        async with factory() as session:
            await set_tenant_context(session, tenant_uuid)
            workspace, document, domain = await _load_workspace_and_domain(
                session,
                tenant_uuid,
                workspace_uuid,
                domain_id,
            )
            if workspace is None or document is None or domain is None:
                return
            hostname = domain.hostname
            if domain.status not in TLS_ELIGIBLE_DOMAIN_STATUSES:
                return
            ready, reason = await check_domain_tls(hostname)
            current = await _refresh_domain_for_result(
                session,
                workspace,
                domain_id,
                hostname=hostname,
                allowed_statuses=TLS_ELIGIBLE_DOMAIN_STATUSES,
            )
            if current is None:
                return
            document, domain = current
            if ready:
                domain.status = "active"
                domain.failure_reason = ""
                action = "workspace.domain.activated"
            else:
                domain.status = "certificate_pending"
                domain.failure_reason = reason
                action = "workspace.domain.certificate.pending"
            save_document(workspace, document)
            await persist_branding_document(session, workspace, document)
            emit_workspace_administrative_event(
                session,
                tenant_id=tenant_uuid,
                workspace_id=workspace_uuid,
                actor_user_id=None,
                action=action,
                resource_type="workspace_custom_domain",
                resource_id=domain.id,
                fields=["status", "failureReason"],
                after={"hostname": hostname, "status": domain.status},
                reason="Asynchronous TLS readiness check",
            )
            await session.commit()
    finally:
        if hostname:
            await invalidate_brand_cache(workspace_uuid, hostnames=[hostname])
        tenant_context.reset(token)
        await engine.dispose()


@celery_app.task(
    name="northstar.verify_workspace_brand_domain",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=5,
)
def verify_custom_domain_dns(tenant_id: str, workspace_id: str, domain_id: str) -> None:
    asyncio.run(_run_dns_verification(tenant_id, workspace_id, domain_id))


@celery_app.task(
    name="northstar.check_workspace_brand_tls",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=5,
)
def check_custom_domain_tls(tenant_id: str, workspace_id: str, domain_id: str) -> None:
    asyncio.run(_run_tls_check(tenant_id, workspace_id, domain_id))
