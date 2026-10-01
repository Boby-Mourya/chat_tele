"""Workspace notification-settings API boundary using the existing handler."""

from fastapi import APIRouter

from northstar_api.modules.workspace.contracts import NotificationSettings
from northstar_api.modules.workspace.settings import update_notifications

router = APIRouter()
router.patch("/notifications", response_model=NotificationSettings)(update_notifications)

__all__ = ["router"]
