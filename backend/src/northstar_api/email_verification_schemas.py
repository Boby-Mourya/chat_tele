from __future__ import annotations

from pydantic import EmailStr, Field

from northstar_api.schemas import APIModel


class EmailVerificationResendRequest(APIModel):
    email: EmailStr


class EmailVerificationVerifyRequest(APIModel):
    token: str = Field(min_length=20, max_length=512)


class EmailVerificationAccepted(APIModel):
    accepted: bool = True


class EmailVerificationResult(APIModel):
    verified: bool = True
    already_verified: bool = False
