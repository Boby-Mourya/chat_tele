"""Workspace role types; custom roles remain the existing validated settings contract.

No new SQLAlchemy role mapping is introduced during the additive migration.
"""

from northstar_api.models import WorkspaceRole
from northstar_api.modules.workspace.contracts import CustomRole, RolesSettings

__all__ = ["CustomRole", "RolesSettings", "WorkspaceRole"]
