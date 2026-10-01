"""Optional canonical access to existing Workspace invitation HTTP routers.

These endpoints are already registered by ``northstar_api.routers`` and are
owned by the teammate's existing invitation pipeline. Do not import or register
these routers from ``modules.workspace.api.__init__``: doing so would create an
initialization cycle and duplicate their production routes. Consumers that need
the canonical invitation location can import this module explicitly.
"""

from northstar_api.routers.workspace_invitations import public_router, router

__all__ = ["public_router", "router"]
