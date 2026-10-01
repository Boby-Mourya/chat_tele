"""Workspace dashboard settings HTTP boundary.

This reuses the existing permission-protected, audited and persisted handler;
legacy access router imports continue working during the staged migration.
"""

from fastapi import APIRouter

from northstar_api.modules.workspace.access import update_dashboard
from northstar_api.modules.workspace.contracts import DashboardSettings

router = APIRouter()
router.patch("/dashboard", response_model=DashboardSettings)(update_dashboard)

__all__ = ["router"]
