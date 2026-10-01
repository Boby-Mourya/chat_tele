from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import event, or_, select
from sqlalchemy.orm import Session, with_loader_criteria

from northstar_api.models import Conversation

from .conversation_assignment_model import WorkspaceConversationAssignment

_SESSION_KEY = "workspace_conversation_assignment_scope"


def set_conversation_assignment_scope(
    session: object,
    *,
    tenant_id: UUID | None = None,
    workspace_id: UUID | None = None,
    user_id: UUID | None = None,
    team_ids: frozenset[str] | None = None,
) -> None:
    """Attach conversation-assignment scope to the current database session.

    With no assignment scope the restriction is removed. Assigned scope filters
    by ``assigned_user_id``; team scope filters by one of the caller's workspace
    team IDs. The tenant/workspace keys are required whenever a scope is active,
    keeping the assignment lookup inside the same boundary as the conversation.
    """
    sync_session = getattr(session, "sync_session", session)
    info = getattr(sync_session, "info", None)
    if info is None:
        return
    normalized_team_ids = frozenset(value for value in (team_ids or frozenset()) if value)
    if user_id is None and not normalized_team_ids:
        info.pop(_SESSION_KEY, None)
        return
    if tenant_id is None or workspace_id is None:
        raise ValueError("Tenant and workspace are required for conversation assignment scope")
    info[_SESSION_KEY] = (tenant_id, workspace_id, user_id, normalized_team_ids)


@event.listens_for(Session, "do_orm_execute")
def apply_conversation_assignment_scope(execute_state: Any) -> None:
    if not execute_state.is_select:
        return
    scope = execute_state.session.info.get(_SESSION_KEY)
    if scope is None:
        return
    tenant_id, workspace_id, user_id, team_ids = scope
    predicates: list[Any] = []
    if user_id is not None:
        predicates.append(WorkspaceConversationAssignment.assigned_user_id == user_id)
    if team_ids:
        predicates.append(WorkspaceConversationAssignment.assigned_team_id.in_(team_ids))
    if not predicates:
        return
    assignment_ids = select(WorkspaceConversationAssignment.conversation_id).where(
        WorkspaceConversationAssignment.tenant_id == tenant_id,
        WorkspaceConversationAssignment.workspace_id == workspace_id,
        or_(*predicates),
    )
    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(
            Conversation,
            Conversation.id.in_(assignment_ids),
            include_aliases=True,
        )
    )
