from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from northstar_api.dependencies import DBSession, get_current_principal
from northstar_api.notifications import Notification
from northstar_api.schemas import APIModel
from northstar_api.security import Principal
from northstar_api.services.notifications import (
    list_notifications,
    mark_all_notifications_read,
    mark_notification_read,
    unread_notification_count,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationOut(APIModel):
    id: UUID
    workspace_id: UUID | None
    category: str
    severity: str
    title: str
    body: str
    action_url: str | None
    action_label: str | None
    metadata: dict[str, object]
    read_at: datetime | None
    created_at: datetime


class UnreadCountOut(APIModel):
    count: int


class MarkAllReadOut(APIModel):
    updated: int


def require_human_notification_principal(
    principal: Annotated[Principal, Depends(get_current_principal)],
) -> Principal:
    if principal.token_id.startswith("api_key:"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API keys do not have a human notification inbox",
        )
    if principal.workspace_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Workspace access is unavailable",
        )
    return principal


HumanPrincipal = Annotated[Principal, Depends(require_human_notification_principal)]


def _out(value: Notification) -> NotificationOut:
    return NotificationOut(
        id=value.id,
        workspace_id=value.workspace_id,
        category=value.category,
        severity=value.severity,
        title=value.title,
        body=value.body,
        action_url=value.action_url,
        action_label=value.action_label,
        metadata=value.metadata_json,
        read_at=value.read_at,
        created_at=value.created_at,
    )


@router.get("", response_model=list[NotificationOut])
async def get_notifications(
    principal: HumanPrincipal,
    session: DBSession,
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[NotificationOut]:
    assert principal.workspace_id is not None
    values = await list_notifications(
        session,
        tenant_id=principal.tenant_id,
        recipient_user_id=principal.user_id,
        workspace_id=principal.workspace_id,
        unread_only=unread_only,
        limit=limit,
    )
    return [_out(value) for value in values]


@router.get("/unread-count", response_model=UnreadCountOut)
async def get_unread_count(
    principal: HumanPrincipal,
    session: DBSession,
) -> UnreadCountOut:
    assert principal.workspace_id is not None
    return UnreadCountOut(
        count=await unread_notification_count(
            session,
            tenant_id=principal.tenant_id,
            recipient_user_id=principal.user_id,
            workspace_id=principal.workspace_id,
        )
    )


@router.patch("/{notification_id}/read", response_model=NotificationOut)
async def read_notification(
    notification_id: UUID,
    principal: HumanPrincipal,
    session: DBSession,
) -> NotificationOut:
    assert principal.workspace_id is not None
    value = await mark_notification_read(
        session,
        tenant_id=principal.tenant_id,
        recipient_user_id=principal.user_id,
        workspace_id=principal.workspace_id,
        notification_id=notification_id,
    )
    if value is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    await session.commit()
    return _out(value)


@router.post("/read-all", response_model=MarkAllReadOut)
async def read_all_notifications(
    principal: HumanPrincipal,
    session: DBSession,
) -> MarkAllReadOut:
    assert principal.workspace_id is not None
    updated = await mark_all_notifications_read(
        session,
        tenant_id=principal.tenant_id,
        recipient_user_id=principal.user_id,
        workspace_id=principal.workspace_id,
    )
    await session.commit()
    return MarkAllReadOut(updated=updated)
