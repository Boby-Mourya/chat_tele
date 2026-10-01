"""Workspace persistence boundary.

The current repository delegates to the compatibility storage helpers so new
feature code no longer imports persistence details directly.
"""

from northstar_api.modules.workspace.store import load_workspace, save_document, settings_document

__all__ = ["load_workspace", "save_document", "settings_document"]
