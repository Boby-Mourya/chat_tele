"""Section 23: split settings registration without changing authorization or API contracts."""

from fastapi import APIRouter
from fastapi.routing import APIRoute

from northstar_api.modules.workspace.api import (
    developer_settings_router,
    general_settings_router,
    notifications_settings_router,
    security_settings_router,
    settings_core_router,
    settings_router,
)
from northstar_api.modules.workspace.contracts import (
    DeveloperSettings,
    GeneralSettings,
    NotificationSettings,
    SecuritySettings,
    WorkspaceSettingsBundle,
)
from northstar_api.modules.workspace.router import router as workspace_router
from northstar_api.modules.workspace.settings import (
    get_capabilities,
    get_settings,
    router as legacy_settings_router,
    update_developer,
    update_general,
    update_notifications,
    update_security,
)


def _route(router: APIRouter, path: str, method: str) -> APIRoute:
    found = [
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == path and method in route.methods
    ]
    assert len(found) == 1, f"Expected exactly one {method} {path}, got {len(found)}"
    return found[0]


def _dependencies(route: APIRoute) -> tuple[object, ...]:
    calls: list[object] = []

    def visit(node: object) -> None:
        for dependency in getattr(node, "dependencies", ()):
            calls.append(dependency.call)
            visit(dependency)

    visit(route.dependant)
    return tuple(calls)


def test_settings_capabilities_preserve_handlers_models_and_nested_permissions() -> None:
    assert settings_router is legacy_settings_router
    cases = (
        ("", "GET", settings_core_router, get_settings, WorkspaceSettingsBundle),
        ("/capabilities", "GET", settings_core_router, get_capabilities, None),
        ("/general", "PATCH", general_settings_router, update_general, GeneralSettings),
        ("/security", "PATCH", security_settings_router, update_security, SecuritySettings),
        ("/notifications", "PATCH", notifications_settings_router, update_notifications, NotificationSettings),
        ("/developer", "PATCH", developer_settings_router, update_developer, DeveloperSettings),
    )
    for path, method, capability, handler, response in cases:
        original = _route(legacy_settings_router, path, method)
        canonical = _route(capability, path, method)
        aggregate = _route(workspace_router, f"/workspace/settings{path}", method)
        assert original.endpoint is canonical.endpoint is aggregate.endpoint is handler
        # /capabilities has an inferred response model; compare it with the
        # original rather than incorrectly assuming FastAPI sets it to None.
        assert original.response_model == canonical.response_model == aggregate.response_model
        if response is not None:
            assert original.response_model is response
        assert original.status_code == canonical.status_code == aggregate.status_code
        assert original.name == canonical.name == aggregate.name
        assert _dependencies(original) == _dependencies(canonical) == _dependencies(aggregate)
    assert len([route for route in settings_core_router.routes if isinstance(route, APIRoute)]) == 2
    for capability in (
        general_settings_router,
        security_settings_router,
        notifications_settings_router,
        developer_settings_router,
    ):
        assert len([route for route in capability.routes if isinstance(route, APIRoute)]) == 1
    # Preserve the original complete settings router for other importers.
    assert len([route for route in legacy_settings_router.routes if isinstance(route, APIRoute)]) == 6


def test_existing_metadata_and_access_routes_remain_registered_once() -> None:
    _route(workspace_router, "/workspace/settings/general/metadata", "GET")
    for path in ("/roles", "/teams", "/dashboard"):
        _route(workspace_router, f"/workspace/settings{path}", "PATCH")
