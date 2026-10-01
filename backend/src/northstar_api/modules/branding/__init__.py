"""Feature-owned white-label/branding boundary.

Keep router exports import-compatible without importing HTTP modules eagerly.
The legacy Workspace branding module imports branding repositories/services
before defining its router; eagerly importing branding.api here can otherwise
re-enter that partially initialized module.
"""

from importlib import import_module
from typing import cast

from fastapi import APIRouter

__all__ = [
    "brand_draft_router",
    "brand_versions_router",
    "branding_router",
    "domains_router",
    "email_router",
]


def __getattr__(name: str) -> APIRouter:
    """Resolve existing and canonical router exports only when requested."""
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return cast(APIRouter, getattr(import_module(f"{__name__}.api"), name))
