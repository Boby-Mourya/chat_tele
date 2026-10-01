from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import EmailStr

from northstar_api.models import Role
from northstar_api.schemas import APIModel


class AuthUserOut(APIModel):
    id: UUID
    name: str
    email: EmailStr
    role: Role
    email_verified: bool


class AuthSessionOut(APIModel):
    access_token: str
    expires_at: datetime
    user: AuthUserOut
    refresh_token: str | None = None


class AuthMFAChallengeOut(APIModel):
    mfa_required: Literal[True] = True
    challenge_token: str
    expires_at: datetime


AuthLoginOut = AuthSessionOut | AuthMFAChallengeOut
