"""Section 23: brand draft and publication routing must preserve legacy behavior."""

from fastapi import APIRouter
from fastapi.routing import APIRoute

from northstar_api.modules.branding.api import (
    brand_draft_router,
    brand_versions_router,
    branding_router,
)
from northstar_api.modules.workspace.branding import (
    get_branding,
    get_runtime_branding,
    publish_branding,
    rollback_branding,
    save_branding_draft,
)
from northstar_api.modules.workspace.contracts import (
    BrandingSettingsView,
    BrandVersion,
    ExtendedBranding,
)
from northstar_api.modules.workspace.router import router as workspace_router


def _single_route(router: APIRouter, path: str, method: str) -> APIRoute:
    matching = [
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == path and method in route.methods
    ]
    assert len(matching) == 1, f"Expected one {method} {path}, got {len(matching)}"
    return matching[0]


def _dependency_calls(route: APIRoute) -> tuple[object, ...]:
    calls: list[object] = []

    def walk(node: object) -> None:
        for dependency in getattr(node, "dependencies", ()):
            calls.append(dependency.call)
            walk(dependency)

    walk(route.dependant)
    return tuple(calls)


def test_branding_capabilities_preserve_handlers_response_models_and_permissions() -> None:
    cases = (
        ("GET", "/branding", brand_draft_router, get_branding, BrandingSettingsView),
        ("GET", "/runtime-branding", brand_draft_router, get_runtime_branding, ExtendedBranding | None),
        ("PATCH", "/branding/draft", brand_draft_router, save_branding_draft, ExtendedBranding),
        ("POST", "/branding/publish", brand_versions_router, publish_branding, BrandVersion),
        ("POST", "/branding/rollback", brand_versions_router, rollback_branding, BrandVersion),
    )
    for method, path, canonical_router, handler, response_model in cases:
        legacy = _single_route(branding_router, path, method)
        canonical = _single_route(canonical_router, path, method)
        registered = _single_route(workspace_router, f"/workspace/settings{path}", method)
        assert legacy.endpoint is canonical.endpoint is registered.endpoint is handler
        assert legacy.response_model is canonical.response_model is registered.response_model == response_model
        assert legacy.name == canonical.name == registered.name
        assert legacy.status_code == canonical.status_code == registered.status_code
        assert _dependency_calls(legacy) == _dependency_calls(canonical) == _dependency_calls(registered)
    assert len(brand_draft_router.routes) == 3
    assert len(brand_versions_router.routes) == 2
    assert len(branding_router.routes) == 5


def test_legacy_branding_router_is_not_registered_a_second_time() -> None:
    for path, method in (
        ("/branding", "GET"),
        ("/runtime-branding", "GET"),
        ("/branding/draft", "PATCH"),
        ("/branding/publish", "POST"),
        ("/branding/rollback", "POST"),
    ):
        _single_route(workspace_router, f"/workspace/settings{path}", method)
