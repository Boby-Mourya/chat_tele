from __future__ import annotations

from pydantic import EmailStr, Field, model_validator

from northstar_api.schemas import APIModel


class PasswordResetRequest(APIModel):
    email: EmailStr


class PasswordResetConfirm(APIModel):
    token: str = Field(min_length=20, max_length=512)
    password: str = Field(min_length=12, max_length=256)
    confirm_password: str = Field(min_length=12, max_length=256)

    @model_validator(mode="after")
    def passwords_match(self) -> PasswordResetConfirm:
        if self.password != self.confirm_password:
            raise ValueError("Passwords do not match")
        return self


class PasswordResetAccepted(APIModel):
    accepted: bool = True


class PasswordResetResult(APIModel):
    reset: bool = True
