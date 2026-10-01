from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field, field_validator

from northstar_api.modules.workspace.api_key_scopes import API_KEY_SCOPES
from northstar_api.schemas import APIModel


class WorkspaceAPIKeyCreate(APIModel):
    name: str = Field(min_length=2, max_length=120)
    scopes: list[str] = Field(default_factory=lambda: ["workspace:read", "conversations:read", "agents:read"], min_length=1, max_length=20)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("must contain at least two visible characters")
        return normalized

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, value: list[str]) -> list[str]:
        scopes = list(dict.fromkeys(value))
        if not set(scopes) <= API_KEY_SCOPES:
            raise ValueError("one or more API key scopes are not supported")
        return sorted(scopes)


class WorkspaceAPIKeyOut(APIModel):
    id: UUID
    name: str
    prefix: str
    scopes: list[str]
    created_at: datetime
    last_used_at: datetime | None = None


class WorkspaceAPIKeyCreated(WorkspaceAPIKeyOut):
    secret: str
