"""Persist Workspace dashboard edits without publishing draft branding.

Call only after tenant authorization and the shared Workspace row write lock.
The API handler retains normalized-brand dual-write, audit/outbox and commit.
"""

from __future__ import annotations

from typing import Any

from northstar_api.models import Workspace
from northstar_api.modules.workspace.contracts import DashboardSettings
from northstar_api.modules.workspace.store import save_document, settings_document


def update_workspace_dashboard(workspace: Workspace, payload: DashboardSettings) -> dict[str, Any]:
    """Update the editable layout and draft brand; preserve published versions."""
    document = settings_document(workspace)
    before = document.dashboard.model_dump(by_alias=True, mode="json")
    document.dashboard = payload
    document.branding_draft.dashboard = payload
    save_document(workspace, document)
    return before
