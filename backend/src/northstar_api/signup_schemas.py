from __future__ import annotations

from typing import Literal

from pydantic import EmailStr, Field, field_validator, model_validator

from northstar_api.schemas import APIModel


class SignupRequest(APIModel):
    """Public self-service or workspace-invitation account creation contract."""

    name: str = Field(min_length=2, max_length=160)
    email: EmailStr
    password: str = Field(min_length=12, max_length=256)
    organization_name: str | None = Field(default=None, min_length=2, max_length=160)
    workspace_invitation_token: str | None = Field(default=None, min_length=32, max_length=256)
    terms_accepted: Literal[True]
    privacy_accepted: Literal[True]

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("must contain at least two visible characters")
        return normalized

    @field_validator("organization_name")
    @classmethod
    def normalize_organization(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("must contain at least two visible characters")
        return normalized

    @field_validator("workspace_invitation_token")
    @classmethod
    def normalize_invitation_token(cls, value: str | None) -> str | None:
        return value.strip() if value else None

    @model_validator(mode="after")
    def require_organization_for_self_service(self) -> SignupRequest:
        if self.workspace_invitation_token is None and not self.organization_name:
            raise ValueError("organizationName is required for self-service signup")
        return self
