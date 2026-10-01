from __future__ import annotations

import json
from typing import Annotated
from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.config import get_settings
from northstar_api.database import get_session, set_tenant_context
from northstar_api.dependencies import bearer
from northstar_api.models import Agent, AgentStatus, Channel, Conversation, Workspace
from northstar_api.modules.workspace.store import settings_document
from northstar_api.schemas import (
    AgentAppearance,
    ChatStreamRequest,
    WidgetBootstrap,
    WidgetMessageRequest,
    WidgetSessionCreate,
    WidgetSessionOut,
)
from northstar_api.security import create_widget_token, decode_token
from northstar_api.services.education_chat import education_chat_coordinator
from northstar_api.services.entitlements import EntitlementError, require_capacity
from northstar_api.services.rate_limit import redis_services
from northstar_api.services.streaming import chat_sse_response

router = APIRouter(prefix="/widget", tags=["widget"])
DB = Annotated[AsyncSession, Depends(get_session)]


def origin_host(origin: str) -> str:
    if not origin:
        return ""
    parsed = urlparse(origin)
    return (parsed.hostname or "").lower()


def widget_request_origin(request: Request) -> str:
    """Return the browser-controlled Origin for a top-level widget-loader request."""
    raw = request.headers.get("origin", "").strip()
    if len(raw) > 2048:
        return ""
    parsed = urlparse(raw)
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        return ""
    host = parsed.hostname.lower()
    try:
        port_value = parsed.port
    except ValueError:
        return ""
    port = f":{port_value}" if port_value else ""
    display_host = f"[{host}]" if ":" in host else host
    return f"{parsed.scheme.lower()}://{display_host}{port}"


def is_origin_allowed(origin: str, allowed_domains: list[str]) -> bool:
    host = origin_host(origin)
    if not host:
        return get_settings().app_env in {"development", "test"}
    if not allowed_domains:
        return False
    for pattern in allowed_domains:
        normalized = pattern.lower().split(":", 1)[0]
        if normalized.startswith("*.") and (host == normalized[2:] or host.endswith("." + normalized[2:])):
            return True
        if host == normalized:
            return True
    return False


async def public_agent(
    session: AsyncSession,
    public_id: str,
    origin: str | None,
) -> Agent:
    if session.bind and session.bind.dialect.name == "postgresql":
        tenant_id = await session.scalar(
            text("SELECT northstar_resolve_public_agent_tenant(:public_id)"),
            {"public_id": public_id},
        )
        if not tenant_id:
            raise HTTPException(status_code=404, detail="Published agent not found")
        await set_tenant_context(session, UUID(str(tenant_id)))
    agent = await session.scalar(
        select(Agent).where(
            Agent.public_id == public_id, Agent.status == AgentStatus.ACTIVE, Agent.deleted_at.is_(None)
        )
    )
    if not agent:
        raise HTTPException(status_code=404, detail="Published agent not found")
    allowed = list(agent.security.get("allowedDomains", []))
    if origin is not None and not is_origin_allowed(origin, allowed):
        raise HTTPException(status_code=403, detail="This origin is not permitted for the widget")
    await set_tenant_context(session, agent.tenant_id)
    return agent


async def _workspace_widget_appearance(session: AsyncSession, agent: Agent) -> AgentAppearance:
    appearance = AgentAppearance.model_validate(agent.appearance)
    workspace = await session.scalar(
        select(Workspace).where(
            Workspace.id == agent.workspace_id,
            Workspace.tenant_id == agent.tenant_id,
        )
    )
    if workspace is None:
        return appearance
    published = settings_document(workspace).branding_published
    if published is None or not published.identity.branded_widget:
        return appearance
    widget = published.widget
    translations = dict(appearance.translations)
    translations.update({
        "offlineMessage": widget.offline_message,
        "launcherIcon": widget.launcher_icon,
        "widgetLogo": widget.widget_logo,
        "userMessageColor": widget.user_message_color,
        "agentMessageColor": widget.agent_message_color,
        "agentAvatar": widget.agent_avatar,
        "botAvatar": widget.bot_avatar,
        "poweredByLabel": widget.powered_by_label,
        "businessHours": json.dumps(widget.business_hours.model_dump(by_alias=True, mode="json"), separators=(",", ":")),
    })
    return appearance.model_copy(
        update={
            "primary_color": widget.launcher_color,
            "surface_color": widget.background,
            "font_family": widget.font,
            "position": widget.position,
            "welcome_title": widget.header or appearance.welcome_title,
            "welcome_message": widget.greeting,
            "privacy_policy_url": widget.privacy_url or appearance.privacy_policy_url,
            "widget_name": published.identity.company_name or appearance.widget_name,
            "show_branding": not published.identity.remove_platform_branding,
            "launcher_style": "avatar" if widget.launcher_icon else appearance.launcher_style,
            "translations": translations,
        }
    )


@router.get("/{public_id}/bootstrap", response_model=WidgetBootstrap)
async def bootstrap_widget(public_id: str, request: Request, session: DB) -> WidgetBootstrap:
    agent = await public_agent(session, public_id, widget_request_origin(request))
    prefix = get_settings().app_api_prefix.rstrip("/")
    return await _widget_bootstrap(session, agent, f"{prefix}/widget/{agent.public_id}/sessions")


@router.get("/{public_id}/hosted/bootstrap", response_model=WidgetBootstrap)
async def bootstrap_hosted_widget(public_id: str, session: DB) -> WidgetBootstrap:
    agent = await public_agent(session, public_id, None)
    prefix = get_settings().app_api_prefix.rstrip("/")
    return await _widget_bootstrap(session, agent, f"{prefix}/widget/{agent.public_id}/hosted/sessions")


async def _widget_bootstrap(
    session: AsyncSession,
    agent: Agent,
    session_endpoint: str,
) -> WidgetBootstrap:
    return WidgetBootstrap(
        agent_id=agent.id,
        public_id=agent.public_id,
        name=agent.name,
        avatar=agent.avatar,
        language=agent.language,
        appearance=await _workspace_widget_appearance(session, agent),
        collect_email=bool(agent.security.get("collectEmail", False)),
        session_endpoint=session_endpoint,
        stream_endpoint="/api/v1/widget/sessions/{conversationId}/messages",
    )


@router.post("/{public_id}/sessions", response_model=WidgetSessionOut, status_code=201)
async def create_widget_session(
    public_id: str,
    request: Request,
    session: DB,
    payload: WidgetSessionCreate | None = None,
) -> WidgetSessionOut:
    payload = payload or WidgetSessionCreate()
    origin = widget_request_origin(request)
    agent = await public_agent(session, public_id, origin)
    return await _create_session(session, agent, payload, origin, request)


@router.post("/{public_id}/hosted/sessions", response_model=WidgetSessionOut, status_code=201)
async def create_hosted_widget_session(
    public_id: str,
    request: Request,
    session: DB,
    payload: WidgetSessionCreate | None = None,
) -> WidgetSessionOut:
    payload = payload or WidgetSessionCreate()
    agent = await public_agent(session, public_id, None)
    return await _create_session(session, agent, payload, "northstar-hosted", request)


async def _create_session(
    session: AsyncSession,
    agent: Agent,
    payload: WidgetSessionCreate,
    deployment_origin: str,
    request: Request,
) -> WidgetSessionOut:
    from northstar_api.services.visitor_details import capture_visitor_details, enrich_location

    limiter = await redis_services.check_rate_limit(
        f"tenant:{agent.tenant_id}:agent:{agent.id}:widget-sessions",
        get_settings().widget_session_rate_limit_per_minute,
        scope="widget_session",
    )
    if not limiter.allowed:
        raise HTTPException(
            status_code=429,
            detail="Widget session capacity exceeded",
            headers={"Retry-After": str(limiter.retry_after)},
        )
    try:
        await require_capacity(session, tenant_id=agent.tenant_id, resource="conversations")
    except EntitlementError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None
    conversation = Conversation(
        tenant_id=agent.tenant_id,
        workspace_id=agent.workspace_id,
        agent_id=agent.id,
        visitor_id=payload.visitor_id,
        visitor_name=payload.visitor_name or "Anonymous visitor",
        visitor_email=str(payload.visitor_email) if payload.visitor_email else None,
        page_url=payload.page_url,
        visitor_details=await enrich_location(capture_visitor_details(request, payload)),
        channel=Channel.WIDGET,
        knowledge_revision=agent.published_knowledge_revision,
    )
    session.add(conversation)
    await session.commit()
    token, expires_at = create_widget_token(
        agent.tenant_id,
        agent.id,
        conversation.id,
        deployment_origin,
    )
    return WidgetSessionOut(
        conversation_id=conversation.id,
        conversation_public_id=conversation.public_id,
        session_token=token,
        expires_at=expires_at,
    )


@router.post("/sessions/{conversation_id}/messages")
async def widget_message(
    conversation_id: UUID,
    payload: WidgetMessageRequest,
    session: DB,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> StreamingResponse:
    if not credentials:
        raise HTTPException(status_code=401, detail="Widget session token required")
    try:
        claims = decode_token(credentials.credentials, "widget")
        claim_conversation = UUID(claims["sub"])
        tenant_id = UUID(claims["tid"])
        agent_id = UUID(claims["aid"])
    except (ValueError, KeyError):
        raise HTTPException(status_code=401, detail="Invalid or expired widget session") from None
    session_origin = str(claims.get("origin", ""))
    if claim_conversation != conversation_id or not session_origin:
        raise HTTPException(status_code=403, detail="Widget session does not match this request")
    await set_tenant_context(session, tenant_id)
    active_agent = await session.scalar(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.tenant_id == tenant_id,
            Agent.status == AgentStatus.ACTIVE,
            Agent.deleted_at.is_(None),
        )
    )
    if not active_agent:
        raise HTTPException(status_code=404, detail="Published agent not found")
    if session_origin != "northstar-hosted" and not is_origin_allowed(
        session_origin, list(active_agent.security.get("allowedDomains", []))
    ):
        raise HTTPException(status_code=403, detail="This widget session is no longer permitted")
    try:
        await require_capacity(session, tenant_id=tenant_id, resource="tokens")
    except EntitlementError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None
    prepared = await education_chat_coordinator.prepare(
        session,
        tenant_id=tenant_id,
        request=ChatStreamRequest(
            agent_id=agent_id,
            conversation_id=conversation_id,
            message=payload.message,
            visitor_id=str(conversation_id),
            idempotency_key=payload.idempotency_key,
        ),
        channel=Channel.WIDGET,
    )
    return chat_sse_response(prepared)
