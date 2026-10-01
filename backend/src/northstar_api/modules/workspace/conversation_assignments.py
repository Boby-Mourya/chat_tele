from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy import delete, select

from northstar_api.dependencies import DBSession, require_permissions
from northstar_api.lead_crm.audit import record_audit_event
from northstar_api.models import Conversation, User, WorkspaceMembership
from northstar_api.onboarding_contract import SetupContract
from northstar_api.security import Principal
from northstar_api.services.outbox import enqueue_event

from .conversation_assignment_model import WorkspaceConversationAssignment
from .member_state import is_member_suspended
from .store import load_workspace, settings_document

router = APIRouter(prefix="/conversation-assignments")
AssignmentPrincipal = Annotated[Principal, Depends(require_permissions("conversations.assign"))]


class ConversationAssignmentWrite(SetupContract):
    user_id: UUID | None = None
    team_id: str | None = Field(default=None, max_length=100)


class ConversationAssignmentOut(SetupContract):
    conversation_id: UUID
    user_id: UUID | None = None
    team_id: str | None = None


class ConversationAssignmentMember(SetupContract):
    id: UUID
    name: str
    email: str
    role: str


class ConversationAssignmentTeam(SetupContract):
    id: str
    name: str


class ConversationAssignmentOptions(SetupContract):
    members: list[ConversationAssignmentMember]
    teams: list[ConversationAssignmentTeam]


async def _conversation(
    session: DBSession,
    principal: Principal,
    conversation_id: UUID,
) -> Conversation:
    conditions = [
        Conversation.id == conversation_id,
        Conversation.tenant_id == principal.tenant_id,
        Conversation.workspace_id == principal.workspace_id,
    ]
    if principal.agent_ids is not None:
        conditions.append(Conversation.agent_id.in_(principal.agent_ids))
    conversation = await session.scalar(select(Conversation).where(*conditions))
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


def _response(
    conversation_id: UUID,
    assignment: WorkspaceConversationAssignment | None,
) -> ConversationAssignmentOut:
    return ConversationAssignmentOut(
        conversation_id=conversation_id,
        user_id=assignment.assigned_user_id if assignment else None,
        team_id=assignment.assigned_team_id if assignment else None,
    )


@router.get("/options", response_model=ConversationAssignmentOptions)
async def assignment_options(
    principal: AssignmentPrincipal,
    session: DBSession,
) -> ConversationAssignmentOptions:
    _, workspace = await load_workspace(principal, session)
    rows = (
        await session.execute(
            select(User, WorkspaceMembership)
            .join(WorkspaceMembership, WorkspaceMembership.user_id == User.id)
            .where(
                WorkspaceMembership.tenant_id == principal.tenant_id,
                WorkspaceMembership.workspace_id == principal.workspace_id,
                User.is_active.is_(True),
            )
            .order_by(User.name, User.email, User.id)
        )
    ).all()
    document = settings_document(workspace)
    return ConversationAssignmentOptions(
        members=[
            ConversationAssignmentMember(
                id=user.id,
                name=user.name,
                email=user.email,
                role=membership.role.value,
            )
            for user, membership in rows
            if not is_member_suspended(workspace.settings_json, user.id)
        ],
        teams=[
            ConversationAssignmentTeam(id=team.id, name=team.name)
            for team in sorted(document.teams.teams, key=lambda value: value.name.lower())
        ],
    )


@router.get("/{conversation_id}", response_model=ConversationAssignmentOut)
async def get_assignment(
    conversation_id: UUID,
    principal: AssignmentPrincipal,
    session: DBSession,
) -> ConversationAssignmentOut:
    await _conversation(session, principal, conversation_id)
    assignment = await session.get(WorkspaceConversationAssignment, conversation_id)
    if assignment is not None and (
        assignment.tenant_id != principal.tenant_id
        or assignment.workspace_id != principal.workspace_id
    ):
        assignment = None
    return _response(conversation_id, assignment)


@router.put("/{conversation_id}", response_model=ConversationAssignmentOut)
async def save_assignment(
    conversation_id: UUID,
    payload: ConversationAssignmentWrite,
    principal: AssignmentPrincipal,
    session: DBSession,
) -> ConversationAssignmentOut:
    conversation = await _conversation(session, principal, conversation_id)
    _, workspace = await load_workspace(principal, session)
    if payload.user_id is not None:
        member = await session.scalar(
            select(WorkspaceMembership)
            .join(User, User.id == WorkspaceMembership.user_id)
            .where(
                WorkspaceMembership.tenant_id == principal.tenant_id,
                WorkspaceMembership.workspace_id == principal.workspace_id,
                WorkspaceMembership.user_id == payload.user_id,
                User.is_active.is_(True),
            )
        )
        if member is None or is_member_suspended(workspace.settings_json, payload.user_id):
            raise HTTPException(
                status_code=422,
                detail="Assigned user must be an active workspace member",
            )
    team_id = (payload.team_id or "").strip() or None
    if team_id is not None:
        valid_team_ids = {team.id for team in settings_document(workspace).teams.teams}
        if team_id not in valid_team_ids:
            raise HTTPException(
                status_code=422,
                detail="Assigned team does not exist in this workspace",
            )

    assignment = await session.get(WorkspaceConversationAssignment, conversation_id)
    before = {
        "userId": (
            str(assignment.assigned_user_id)
            if assignment and assignment.assigned_user_id
            else None
        ),
        "teamId": assignment.assigned_team_id if assignment else None,
    }
    if payload.user_id is None and team_id is None:
        if assignment is not None:
            await session.delete(assignment)
        saved: WorkspaceConversationAssignment | None = None
    else:
        if assignment is None:
            assignment = WorkspaceConversationAssignment(
                conversation_id=conversation.id,
                tenant_id=principal.tenant_id,
                workspace_id=principal.workspace_id,
                assigned_user_id=payload.user_id,
                assigned_team_id=team_id,
            )
            session.add(assignment)
        else:
            assignment.assigned_user_id = payload.user_id
            assignment.assigned_team_id = team_id
            assignment.updated_at = datetime.now(UTC)
        saved = assignment

    after = {
        "userId": str(payload.user_id) if payload.user_id else None,
        "teamId": team_id,
    }
    record_audit_event(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id,
        action="workspace.conversation.assignment.updated",
        entity_type="conversation",
        entity_id=str(conversation.id),
        category="conversation",
        before=before,
        after=after,
    )
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="conversation",
        aggregate_id=conversation.id,
        event_type="workspace.conversation.assignment.updated.v1",
        payload={
            "workspaceId": str(principal.workspace_id),
            "conversationId": str(conversation.id),
            **after,
        },
    )
    await session.commit()
    return _response(conversation_id, saved)


@router.delete("/{conversation_id}", response_model=ConversationAssignmentOut)
async def clear_assignment(
    conversation_id: UUID,
    principal: AssignmentPrincipal,
    session: DBSession,
) -> ConversationAssignmentOut:
    await _conversation(session, principal, conversation_id)
    assignment = await session.get(WorkspaceConversationAssignment, conversation_id)
    before = {
        "userId": (
            str(assignment.assigned_user_id)
            if assignment and assignment.assigned_user_id
            else None
        ),
        "teamId": assignment.assigned_team_id if assignment else None,
    }
    await session.execute(
        delete(WorkspaceConversationAssignment).where(
            WorkspaceConversationAssignment.conversation_id == conversation_id,
            WorkspaceConversationAssignment.tenant_id == principal.tenant_id,
            WorkspaceConversationAssignment.workspace_id == principal.workspace_id,
        )
    )
    record_audit_event(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id,
        action="workspace.conversation.assignment.cleared",
        entity_type="conversation",
        entity_id=str(conversation_id),
        category="conversation",
        before=before,
        after={},
    )
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="conversation",
        aggregate_id=conversation_id,
        event_type="workspace.conversation.assignment.cleared.v1",
        payload={
            "workspaceId": str(principal.workspace_id),
            "conversationId": str(conversation_id),
        },
    )
    await session.commit()
    return ConversationAssignmentOut(conversation_id=conversation_id)
