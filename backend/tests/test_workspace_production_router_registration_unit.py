"""Section 23: check the actual application's aggregate API, not only feature routers."""

from fastapi import APIRouter
from fastapi.routing import APIRoute

from northstar_api.modules.workspace.router import router as workspace_router
from northstar_api.routers import api_router
from northstar_api.services.entitlement_guard import enforce_plan_entitlements


_WORKSPACE_ENDPOINTS = (
    ("GET", "/workspace/settings"),
    ("GET", "/workspace/settings/capabilities"),
    ("PATCH", "/workspace/settings/general"),
    ("PATCH", "/workspace/settings/security"),
    ("PATCH", "/workspace/settings/notifications"),
    ("PATCH", "/workspace/settings/developer"),
    ("GET", "/workspace/settings/general/metadata"),
    ("PATCH", "/workspace/settings/roles"),
    ("PATCH", "/workspace/settings/teams"),
    ("PATCH", "/workspace/settings/dashboard"),
    ("GET", "/workspace/settings/branding"),
    ("GET", "/workspace/settings/runtime-branding"),
    ("PATCH", "/workspace/settings/branding/draft"),
    ("POST", "/workspace/settings/branding/publish"),
    ("POST", "/workspace/settings/branding/rollback"),
    ("POST", "/workspace/settings/domains"),
    ("POST", "/workspace/settings/branding/email/preview"),
    ("POST", "/workspace/settings/branding/email/test"),
)


def _route(router: APIRouter, path: str, method: str) -> APIRoute:
    matching = [
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == path and method in route.methods
    ]
    assert len(matching) == 1, f"Expected one production {method} {path}, got {len(matching)}"
    return matching[0]


def _dependencies(route: APIRoute) -> list[object]:
    calls: list[object] = []

    def visit(node: object) -> None:
        for dependency in getattr(node, "dependencies", ()):
            calls.append(dependency.call)
            visit(dependency)

    visit(route.dependant)
    return calls


def test_production_workspace_routes_are_unique_and_preserve_global_entitlements() -> None:
    for method, path in _WORKSPACE_ENDPOINTS:
        canonical = _route(workspace_router, path, method)
        production = _route(api_router, path, method)
        assert production.endpoint is canonical.endpoint
        assert production.response_model is canonical.response_model
        assert production.status_code == canonical.status_code
        production_dependencies = _dependencies(production)
        assert enforce_plan_entitlements in production_dependencies
        for authorization in _dependencies(canonical):
            assert authorization in production_dependencies
