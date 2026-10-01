"""HTTP routers for workspace white-label capabilities.

Keep combined legacy routers available; the Workspace aggregate registers only
canonical capability routers so no branding endpoint is registered twice.
"""

from northstar_api.modules.workspace.branding import router as branding_router
from .domain_routes import router as domains_router
from northstar_api.modules.workspace.email_routes import router as email_router

from .brand_draft import router as brand_draft_router
from .brand_versions import router as brand_versions_router

__all__ = [
    "brand_draft_router",
    "brand_versions_router",
    "branding_router",
    "domains_router",
    "email_router",
]
