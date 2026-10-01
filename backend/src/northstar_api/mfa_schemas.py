from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from northstar_api.schemas import APIModel


class MFAStatusOut(APIModel):
    configured: bool
    enabled: bool
    confirmed_at: datetime | None = None
    unused_recovery_codes: int = 0


class MFASetupRequest(APIModel):
    current_password: str = Field(min_length=8, max_length=256)


class MFASetupOut(APIModel):
    secret: str
    otpauth_uri: str
    recovery_codes: list[str]


class MFAConfirmRequest(APIModel):
    code: str = Field(pattern=r"^\d{6}$")


class MFAChallengeOut(APIModel):
    mfa_required: Literal[True] = True
    challenge_token: str
    expires_at: datetime


class MFAVerifyRequest(APIModel):
    challenge_token: str = Field(min_length=20, max_length=4096)
    code: str | None = Field(default=None, pattern=r"^\d{6}$")
    recovery_code: str | None = Field(default=None, min_length=8, max_length=32)

    @model_validator(mode="after")
    def require_one_factor(self) -> MFAVerifyRequest:
        if (self.code is None) == (self.recovery_code is None):
            raise ValueError("Provide exactly one MFA code or recovery code")
        return self


class MFAProtectedActionRequest(APIModel):
    current_password: str = Field(min_length=8, max_length=256)
    code: str | None = Field(default=None, pattern=r"^\d{6}$")
    recovery_code: str | None = Field(default=None, min_length=8, max_length=32)

    @model_validator(mode="after")
    def require_one_factor(self) -> MFAProtectedActionRequest:
        if (self.code is None) == (self.recovery_code is None):
            raise ValueError("Provide exactly one MFA code or recovery code")
        return self


class MFARecoveryCodesOut(APIModel):
    recovery_codes: list[str]
