from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import EmailStr, Field, model_validator

from northstar_api.auth_session_schemas import AuthSessionOut
from northstar_api.models import WorkspaceRole
from northstar_api.schemas import APIModel
from northstar_api.workspace_invitations import WorkspaceInvitationStatus


class WorkspaceInvitationCreate(APIModel):
    email: EmailStr
    role: WorkspaceRole = WorkspaceRole.OPERATOR
    all_agents_access: bool = True
    agent_ids: list[UUID] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_agent_scope(self) -> WorkspaceInvitationCreate:
        if self.all_agents_access and self.agent_ids:
            raise ValueError("agentIds must be empty when allAgentsAccess is enabled")
        if len(set(self.agent_ids)) != len(self.agent_ids):
            raise ValueError("agentIds must not contain duplicates")
        return self


class WorkspaceMemberPatch(APIModel):
    role: WorkspaceRole
    all_agents_access: bool = True
    agent_ids: list[UUID] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_agent_scope(self) -> WorkspaceMemberPatch:
        if self.all_agents_access and self.agent_ids:
            raise ValueError("agentIds must be empty when allAgentsAccess is enabled")
        if len(set(self.agent_ids)) != len(self.agent_ids):
            raise ValueError("agentIds must not contain duplicates")
        return self


class WorkspaceMemberOut(APIModel):
    user_id: UUID
    name: str
    email: EmailStr
    role: WorkspaceRole
    all_agents_access: bool
    agent_ids: list[UUID]
    joined_at: datetime
    is_self: bool


class WorkspaceInvitationOut(APIModel):
    id: UUID
    email: EmailStr
    role: WorkspaceRole
    all_agents_access: bool
    agent_ids: list[UUID]
    status: WorkspaceInvitationStatus
    expires_at: datetime
    last_sent_at: datetime | None
    delivery_attempts: int
    delivery_state: Literal["not-sent", "sent", "failed"]
    created_at: datetime


class WorkspaceInvitationTokenRequest(APIModel):
    token: str = Field(min_length=32, max_length=512)


class WorkspaceInvitationPreview(APIModel):
    invitation_id: UUID
    email: EmailStr
    tenant_id: UUID
    tenant_name: str
    tenant_slug: str
    workspace_id: UUID
    workspace_name: str
    role: WorkspaceRole
    all_agents_access: bool
    agent_count: int
    expires_at: datetime
    existing_user: bool


class WorkspaceInvitationDeclined(APIModel):
    declined: Literal[True] = True


class WorkspaceInvitationSignupRequest(WorkspaceInvitationTokenRequest):
    name: str = Field(min_length=2, max_length=160)
    password: str = Field(min_length=12, max_length=256)
    terms_accepted: Literal[True]
    privacy_accepted: Literal[True]


class WorkspaceInvitationSessionOut(AuthSessionOut):
    tenant_id: UUID
    tenant_slug: str
    workspace_id: UUID
