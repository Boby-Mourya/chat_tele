from __future__ import annotations

from typing import Literal
from uuid import UUID

_STATUS_KEY = "workspaceMemberStatusV1"


def member_statuses(workspace_settings: dict[str, object] | None) -> dict[str, str]:
    raw = dict(workspace_settings or {}).get(_STATUS_KEY, {})
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items() if value in {"active", "suspended"}}


def is_member_suspended(workspace_settings: dict[str, object] | None, user_id: UUID) -> bool:
    return member_statuses(workspace_settings).get(str(user_id)) == "suspended"


def save_member_status(
    workspace_settings: dict[str, object] | None,
    user_id: UUID,
    status: Literal["active", "suspended"],
) -> dict[str, object]:
    settings: dict[str, object] = dict(workspace_settings or {})
    statuses = member_statuses(settings)
    if status == "active":
        statuses.pop(str(user_id), None)
    else:
        statuses[str(user_id)] = status
    settings[_STATUS_KEY] = statuses
    return settings
