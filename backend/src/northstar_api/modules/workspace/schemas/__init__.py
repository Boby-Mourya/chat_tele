"""Workspace-owned API and persistence schemas.

This package is the stable import surface for new workspace code. The concrete
Pydantic models remain in ``contracts`` during the compatibility phase.
"""

from northstar_api.modules.workspace.contracts import *  # noqa: F403
