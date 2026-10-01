from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from northstar_api import __version__
from northstar_api.config import get_settings
from northstar_api.database import (
    SessionFactory,
    close_database,
    initialize_schema,
    set_tenant_context,
    tenant_context,
)
from northstar_api.health import router as health_router
from northstar_api.help_config import get_help_settings
from northstar_api.lead_crm.audit import AuditCategory, AuditOutcome, AuditSeverity, record_audit_event
from northstar_api.logging import configure_logging, request_id_ctx
from northstar_api.middleware import RequestContextMiddleware
from northstar_api.routers import api_router
from northstar_api.security import Principal
from northstar_api.services.help_content import sync_help_content
from northstar_api.services.rate_limit import redis_services
from northstar_api.services.seed import seed_from_environment

settings = get_settings()
help_settings = get_help_settings()
configure_logging(settings)
logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if settings.app_auto_create_schema:
        await initialize_schema()
    async with SessionFactory() as session:
        await seed_from_environment(session, settings)
        if help_settings.help_content_sync_on_startup:
            await sync_help_content(session)
    logger.info("application_started", version=__version__, environment=settings.app_env)
    try:
        yield
    finally:
        await redis_services.close()
        await close_database()
        logger.info("application_stopped")


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    default_response_class=JSONResponse,
    lifespan=lifespan,
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
)
app.add_middleware(RequestContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.app_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Idempotency-Key",
        "X-Request-ID",
        "X-Workspace-ID",
    ],
    expose_headers=["X-Request-ID", "Retry-After"],
)


def _is_public_widget_cors_path(path: str) -> bool:
    prefixes = {f"{settings.app_api_prefix.rstrip('/')}/widget/", "/v1/widget/"}
    for prefix in prefixes:
        if not path.startswith(prefix):
            continue
        parts = path[len(prefix) :].strip("/").split("/")
        return len(parts) == 2 and parts[0] != "sessions" and parts[1] in {"bootstrap", "sessions"}
    return False


def _widget_cors_headers(origin: str) -> dict[str, str]:
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Accept, Content-Type",
        "Access-Control-Max-Age": "600",
        "Vary": "Origin",
    }


def _relative_api_path(path: str) -> str:
    for prefix in (settings.app_api_prefix.rstrip("/"), "/v1"):
        if path == prefix:
            return "/"
        if path.startswith(prefix + "/"):
            return path[len(prefix) :]
    return path


def _audit_category(path: str) -> AuditCategory:
    if path.startswith(("/auth", "/mfa", "/password", "/email-verification")):
        return "security"
    if path.startswith(("/workspace/invitations", "/workspace/members")):
        return "access"
    if path.startswith(("/workspace/api-keys", "/chat/completions")):
        return "api"
    if path.startswith(("/workspace", "/workspaces")):
        return "workspace"
    if path.startswith("/agents"):
        return "agent"
    if path.startswith(("/conversations", "/messages", "/chat")):
        return "conversation"
    if path.startswith("/education"):
        return "education"
    if path.startswith(("/leads", "/qualification")):
        return "lead"
    if path.startswith("/crm"):
        return "crm"
    if path.startswith(("/channels", "/whatsapp", "/widget")):
        return "channel"
    if path.startswith("/billing"):
        return "billing"
    if path.startswith("/integrations"):
        return "integration"
    return "system"


def _audit_outcome(status_code: int) -> tuple[AuditOutcome, AuditSeverity]:
    if status_code < 400:
        return "success", "info"
    if status_code in {401, 403}:
        return "denied", "warning"
    if status_code >= 500:
        return "failure", "critical"
    return "failure", "warning"


@app.middleware("http")
async def security_headers(request: Request, call_next: RequestResponseEndpoint) -> Response:
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), geolocation=(), payment=()")
    if settings.is_production:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


@app.middleware("http")
async def authenticated_mutation_audit(request: Request, call_next: RequestResponseEndpoint) -> Response:
    """Append a safe audit envelope for authenticated state-changing API requests.

    Domain-specific audit events continue to be emitted by existing CRM/integration
    code. This generic envelope intentionally stores no request/response body, so it
    cannot duplicate secrets or change business transaction behavior. Audit write
    failures are observable but never allowed to fail the completed customer action.
    """
    response = await call_next(request)
    method = request.method.upper()
    if method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return response

    path = _relative_api_path(request.url.path)
    if path.startswith(("/audit", "/integration-audit")):
        return response
    principal = getattr(request.state, "principal", None)
    if not isinstance(principal, Principal):
        return response

    category = _audit_category(path)
    outcome, severity = _audit_outcome(response.status_code)
    route = request.scope.get("route")
    route_path = str(getattr(route, "path", path))
    credential_type = "api_key" if principal.token_id.startswith("api_key:") else "session"
    context_token = tenant_context.set(None)
    try:
        async with SessionFactory() as session:
            await set_tenant_context(session, principal.tenant_id)
            record_audit_event(
                session,
                tenant_id=principal.tenant_id,
                workspace_id=principal.workspace_id,
                actor_user_id=principal.platform_actor_id or principal.user_id,
                action=f"{category}.{method.lower()}",
                entity_type=category,
                entity_id=route_path,
                category=category,
                severity=severity,
                outcome=outcome,
                metadata={
                    "method": method,
                    "route": route_path,
                    "statusCode": response.status_code,
                    "credentialType": credential_type,
                    **({"actingAsUserId": str(principal.user_id), "impersonationId": principal.impersonation_id} if principal.platform_actor_id else {}),
                },
                request=request,
            )
            await session.commit()
    except Exception as exc:  # audit observability must never break a completed mutation
        logger.warning(
            "audit_event_write_failed",
            path=route_path,
            method=method,
            error=type(exc).__name__,
        )
    finally:
        tenant_context.reset(context_token)
    return response


@app.middleware("http")
async def public_widget_cors(request: Request, call_next: RequestResponseEndpoint) -> Response:
    """Expose bootstrap/session responses only to the browser Origin accepted by the route.

    Preflight is intentionally non-authorizing: the subsequent request still performs
    the per-agent domain check before any response receives an allow-origin header.
    """
    if not _is_public_widget_cors_path(request.url.path):
        return await call_next(request)

    from northstar_api.routers.widget import widget_request_origin

    origin = widget_request_origin(request)
    if request.method == "OPTIONS":
        requested_method = request.headers.get("access-control-request-method", "").upper()
        if not origin or requested_method not in {"GET", "POST"}:
            return Response(status_code=400)
        return Response(status_code=204, headers=_widget_cors_headers(origin))

    response = await call_next(request)
    if origin and 200 <= response.status_code < 300:
        for name, value in _widget_cors_headers(origin).items():
            response.headers[name] = value
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) else "Request could not be completed"
    return JSONResponse(
        {"error": {"code": f"http_{exc.status_code}", "message": message, "requestId": request_id_ctx.get()}},
        status_code=exc.status_code,
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [
        {"field": ".".join(str(part) for part in error["loc"]), "message": error["msg"]}
        for error in exc.errors()
    ]
    return JSONResponse(
        {
            "error": {
                "code": "validation_error",
                "message": "Request validation failed",
                "requestId": request_id_ctx.get(),
                "fields": errors,
            }
        },
        status_code=422,
    )


app.include_router(health_router)
app.include_router(api_router, prefix=settings.app_api_prefix)
# Compatibility alias for clients configured with the documented /v1 base.
if settings.app_api_prefix != "/v1":
    app.include_router(api_router, prefix="/v1", include_in_schema=False)


def run() -> None:
    uvicorn.run("northstar_api.main:app", host=settings.app_host, port=settings.app_port, reload=False)


if __name__ == "__main__":
    run()
