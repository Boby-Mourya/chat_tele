"""Section 23: split API registration without changing any legacy Workspace endpoint."""

from fastapi import APIRouter
from fastapi.routing import APIRoute

from northstar_api.modules.workspace.access import (
    router as legacy_access_router,
    update_dashboard,
    update_roles,
    update_teams,
)
from northstar_api.modules.workspace.api import (
    access_router,
    dashboard_settings_router,
    roles_router,
    teams_router,
)
from northstar_api.modules.workspace.contracts import DashboardSettings, RolesSettings, TeamsSettings
from northstar_api.modules.workspace.router import router as workspace_router


def _patch_route(router: APIRouter, path: str) -> APIRoute:
    matching = [
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == path and route.methods == {"PATCH"}
    ]
    assert len(matching) == 1, f"Expected exactly one PATCH {path}, found {len(matching)}"
    return matching[0]


def _dependency_calls(route: APIRoute) -> tuple[object, ...]:
    """Include nested authorization calls, not merely the endpoint function."""
    calls: list[object] = []

    def visit(node: object) -> None:
        for dependency in getattr(node, "dependencies", ()):  # FastAPI Dependant tree.
            calls.append(dependency.call)
            visit(dependency)

    visit(route.dependant)
    return tuple(calls)


def test_capability_routers_preserve_legacy_handlers_and_response_contracts() -> None:
    assert access_router is legacy_access_router
    for path, feature_router, handler, response_type in (
        ("/roles", roles_router, update_roles, RolesSettings),
        ("/teams", teams_router, update_teams, TeamsSettings),
        ("/dashboard", dashboard_settings_router, update_dashboard, DashboardSettings),
    ):
        legacy = _patch_route(legacy_access_router, path)
        canonical = _patch_route(feature_router, path)
        registered = _patch_route(workspace_router, f"/workspace/settings{path}")
        assert legacy.endpoint is canonical.endpoint is registered.endpoint is handler
        assert legacy.response_model is canonical.response_model is registered.response_model is response_type
        assert legacy.status_code == canonical.status_code == registered.status_code
        assert legacy.name == canonical.name == registered.name
        assert _dependency_calls(legacy) == _dependency_calls(canonical) == _dependency_calls(registered)
        assert len(feature_router.routes) == 1


def test_split_routes_do_not_register_duplicate_access_endpoints() -> None:
    for path in ("/roles", "/teams", "/dashboard"):
        _patch_route(workspace_router, f"/workspace/settings{path}")
    # Existing combined router remains available without being registered again.
    assert len([route for route in legacy_access_router.routes if isinstance(route, APIRoute)]) == 3
