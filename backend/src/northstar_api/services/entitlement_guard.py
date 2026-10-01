from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import func, select

from northstar_api.config import get_settings
from northstar_api.dependencies import DBSession, bearer, get_current_principal
from northstar_api.models import Message, MessageRole, TenantMembership, User
from northstar_api.services.entitlements import (
    EntitlementError,
    require_capacity,
    require_channel,
    require_feature,
)
from northstar_api.workspace_invitations import WorkspaceInvitation, WorkspaceInvitationStatus

Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]


def _relative_path(path: str) -> str:
    prefixes = (get_settings().app_api_prefix.rstrip("/"), "/v1")
    for prefix in prefixes:
        if path == prefix:
            return "/"
        if path.startswith(prefix + "/"):
            return path[len(prefix) :]
    return path


async def _json_body(request: Request) -> dict[str, Any]:
    try:
        value = await request.json()
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _http(exc: EntitlementError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


async def _needs_new_member_seat(session: DBSession, tenant_id: UUID, email: str) -> bool:
    normalized = email.strip().lower()
    if not normalized:
        return True
    existing = await session.scalar(
        select(TenantMembership.user_id)
        .join(User, User.id == TenantMembership.user_id)
        .where(
            TenantMembership.tenant_id == tenant_id,
            func.lower(User.email) == normalized,
        )
    )
    if existing is not None:
        return False
    pending = await session.scalar(
        select(WorkspaceInvitation.id).where(
            WorkspaceInvitation.tenant_id == tenant_id,
            func.lower(WorkspaceInvitation.email) == normalized,
            WorkspaceInvitation.status == WorkspaceInvitationStatus.PENDING,
        )
    )
    return pending is None


async def _is_chat_retry(session: DBSession, tenant_id: UUID, body: dict[str, Any]) -> bool:
    key = body.get("idempotencyKey") or body.get("idempotency_key")
    if not isinstance(key, str) or not key:
        return False
    existing = await session.scalar(
        select(Message.id).where(
            Message.tenant_id == tenant_id,
            Message.idempotency_key == key,
            Message.role == MessageRole.USER,
        )
    )
    return existing is not None


async def enforce_plan_entitlements(
    request: Request,
    credentials: Credentials,
    session: DBSession,
) -> None:
    """Enforce tenant plan policy at existing authenticated write boundaries.

    The dependency is attached once at API composition. It returns immediately for
    routes that do not consume plan capacity, so existing route RBAC remains the
    authority for authentication/authorization. Selected writes authenticate with
    the same principal resolver as the route before applying plan policy.
    """
    path = _relative_path(request.url.path)
    method = request.method.upper()
    body: dict[str, Any] | None = None

    guarded = (
        (
            method == "POST"
            and path
            in {
                "/workspaces",
                "/agents",
                "/workspace/invitations",
                "/workspace/api-keys",
                "/channels/connections",
                "/uploads/presign",
                "/chat/stream",
                "/chat/completions",
            }
        )
        or (method == "POST" and path.startswith("/agents/") and path.endswith("/knowledge"))
        or (method == "PATCH" and path == "/workspace")
        or (method in {"POST", "PUT", "PATCH"} and path.startswith("/crm/"))
    )
    if not guarded:
        return
    if credentials is None:
        return  # Let the existing route return its normal authentication error.

    try:
        principal = await get_current_principal(request, credentials, session)
    except HTTPException:
        return  # Preserve the route's existing authentication error semantics.

    try:
        if method == "POST" and path == "/workspaces":
            await require_capacity(session, tenant_id=principal.tenant_id, resource="workspaces")
            return

        if method == "POST" and path == "/agents":
            await require_capacity(session, tenant_id=principal.tenant_id, resource="agents")
            body = await _json_body(request)
            raw_channel = str(
                body.get("deploymentChannel") or body.get("deployment_channel") or "website"
            )
            provider = {"website": "widget", "facebook": "facebook_messenger"}.get(
                raw_channel, raw_channel
            )
            await require_channel(session, tenant_id=principal.tenant_id, provider=provider)
            return

        if method == "POST" and path == "/workspace/invitations":
            body = await _json_body(request)
            if await _needs_new_member_seat(
                session, principal.tenant_id, str(body.get("email") or "")
            ):
                await require_capacity(session, tenant_id=principal.tenant_id, resource="members")
            return

        if method == "POST" and path == "/workspace/api-keys":
            await require_feature(session, tenant_id=principal.tenant_id, feature="api")
            return

        if method == "POST" and path == "/channels/connections":
            body = await _json_body(request)
            provider = str(body.get("provider") or "")
            if provider:
                await require_channel(session, tenant_id=principal.tenant_id, provider=provider)
            return

        if method in {"POST", "PUT", "PATCH"} and path.startswith("/crm/"):
            await require_feature(session, tenant_id=principal.tenant_id, feature="crm")
            return

        if method == "PATCH" and path == "/workspace":
            body = await _json_body(request)
            if "whiteLabel" in body or "white_label" in body:
                await require_feature(session, tenant_id=principal.tenant_id, feature="white_label")
            return

        if method == "POST" and path == "/uploads/presign":
            body = await _json_body(request)
            requested_bytes = int(body.get("sizeBytes") or body.get("size_bytes") or 0)
            await require_capacity(
                session,
                tenant_id=principal.tenant_id,
                resource="storage",
                additional=max(0, requested_bytes),
            )
            return

        if method == "POST" and path.startswith("/agents/") and path.endswith("/knowledge"):
            body = await _json_body(request)
            content = body.get("content")
            kind = str(body.get("kind") or "").lower()
            if isinstance(content, str) and content:
                additional = len(content.encode("utf-8"))
            elif kind in {"url", "sitemap"}:
                # Remote content has no byte size before fetch. Reserve the maximum
                # configured extraction footprint; the usage service releases the
                # reservation after chunks are written or the remote source fails.
                additional = get_settings().knowledge_max_extracted_characters * 4
            else:
                additional = 0
            if additional:
                await require_capacity(
                    session,
                    tenant_id=principal.tenant_id,
                    resource="storage",
                    additional=additional,
                )
            return

        if method == "POST" and path in {"/chat/stream", "/chat/completions"}:
            if path == "/chat/completions":
                await require_feature(session, tenant_id=principal.tenant_id, feature="api")
            await require_capacity(session, tenant_id=principal.tenant_id, resource="tokens")
            body = await _json_body(request)
            conversation_id = body.get("conversationId") or body.get("conversation_id")
            if path == "/chat/completions" or (
                not conversation_id and not await _is_chat_retry(session, principal.tenant_id, body)
            ):
                await require_capacity(session, tenant_id=principal.tenant_id, resource="conversations")
            return
    except (EntitlementError, ValueError, TypeError) as exc:
        if isinstance(exc, EntitlementError):
            raise _http(exc) from None
        # Payload validation remains the route/schema responsibility.
        return
