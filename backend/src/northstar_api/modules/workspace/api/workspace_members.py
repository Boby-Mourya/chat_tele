"""Canonical Workspace member lifecycle HTTP boundary.

Keep all existing handlers, access checks, and URLs in the legacy module during
the additive migration; this export has no new route-registration side effects.
"""

from northstar_api.modules.workspace.members import router

__all__ = ["router"]
