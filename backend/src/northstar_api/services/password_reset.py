from __future__ import annotations

import asyncio
import hashlib
import html
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from urllib.parse import quote
from uuid import UUID

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.config import get_settings
from northstar_api.email_config import EmailSettings, get_email_settings
from northstar_api.models import User, Workspace
from northstar_api.password_reset import PasswordCredentialState, PasswordResetToken
from northstar_api.security import hash_password, verify_password
from northstar_api.services.smtp import smtp_send

logger = structlog.get_logger(__name__)


class PasswordResetError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class IssuedPasswordReset:
    token: str
    expires_at: datetime


def _token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def credential_version(session: AsyncSession, user_id: UUID) -> int:
    state = await session.get(PasswordCredentialState, user_id)
    return state.version if state is not None else 0


async def issue_password_reset_token(
    session: AsyncSession,
    user_id: UUID,
    *,
    settings: EmailSettings | None = None,
) -> IssuedPasswordReset:
    config = settings or get_email_settings()
    now = datetime.now(UTC)

    # Serialize issuance per account. Without this lock, simultaneous recovery
    # requests could both invalidate the old set and then leave two live links.
    locked_user = await session.scalar(select(User.id).where(User.id == user_id).with_for_update())
    if locked_user is None:
        raise PasswordResetError("Password reset request is unavailable")

    await session.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == user_id,
            PasswordResetToken.consumed_at.is_(None),
        )
        .values(consumed_at=now)
    )
    raw_token = secrets.token_urlsafe(48)
    expires_at = now + timedelta(minutes=config.password_reset_ttl_minutes)
    session.add(
        PasswordResetToken(
            user_id=user_id,
            token_hash=_token_hash(raw_token),
            expires_at=expires_at,
        )
    )
    await session.flush()
    return IssuedPasswordReset(token=raw_token, expires_at=expires_at)


async def reset_password_with_token(
    session: AsyncSession,
    raw_token: str,
    new_password: str,
) -> UUID:
    # Lock the challenge before inspecting consumed_at. This makes one-time use
    # atomic when two confirmation requests race against the same reset link.
    token = await session.scalar(
        select(PasswordResetToken)
        .where(PasswordResetToken.token_hash == _token_hash(raw_token))
        .with_for_update()
    )
    if token is None:
        raise PasswordResetError("Password reset link is invalid or expired")

    now = datetime.now(UTC)
    expires_at = token.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if token.consumed_at is not None or expires_at <= now:
        raise PasswordResetError("Password reset link is invalid or expired")

    user = await session.scalar(
        select(User).where(User.id == token.user_id, User.is_active.is_(True)).with_for_update()
    )
    if user is None:
        raise PasswordResetError("Password reset link is invalid or expired")
    if await asyncio.to_thread(verify_password, new_password, user.password_hash):
        raise PasswordResetError("Choose a password different from your current password")

    user.password_hash = await asyncio.to_thread(hash_password, new_password)
    state = await session.get(PasswordCredentialState, user.id)
    if state is None:
        state = PasswordCredentialState(user_id=user.id, version=1)
        session.add(state)
    else:
        state.version += 1
        state.updated_at = now

    await session.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.consumed_at.is_(None),
        )
        .values(consumed_at=now)
    )
    await session.flush()
    return user.id


def password_reset_url(raw_token: str, settings: EmailSettings | None = None) -> str:
    config = settings or get_email_settings()
    base = config.password_reset_frontend_url.split("#", 1)[0]
    return f"{base}#token={quote(raw_token, safe='')}"


async def send_password_reset_email(
    user: User,
    raw_token: str,
    *,
    workspace: Workspace | None = None,
    settings: EmailSettings | None = None,
) -> None:
    from northstar_api.modules.workspace.email_branding import deliver_workspace_email, render_workspace_email

    config = settings or get_email_settings()
    url = password_reset_url(raw_token, config)
    if workspace is not None:
        from northstar_api.modules.workspace.email_branding import (
            deliver_workspace_email,
            render_workspace_email,
        )

        rendered = render_workspace_email(
            workspace,
            "password_reset",
            context={"user_name": user.name, "user_email": user.email},
            action_url=url,
            fallback_subject="Reset your password",
            fallback_heading="Reset your password",
            fallback_body=(
                "We received a request to reset your password. "
                f"This link expires in {config.password_reset_ttl_minutes} minutes. "
                "If you did not request a password reset, you can ignore this email."
            ),
            fallback_button_label="Reset password",
        )
        await deliver_workspace_email(user.email, rendered, settings=config)
        return
    if config.email_delivery_mode == "log":
        if get_settings().is_production:
            raise PasswordResetError("Email delivery is not configured")
        logger.info(
            "password_reset_email_development",
            user_id=str(user.id),
            email=user.email,
            password_reset_url=url,
        )
        return

    message = EmailMessage()
    message["Subject"] = "Reset your Northstar password"
    message["From"] = f"{config.email_from_name} <{config.email_from_address}>"
    message["To"] = user.email
    message.set_content(
        f"Hi {user.name},\n\n"
        "We received a request to reset your Northstar password.\n\n"
        f"{url}\n\n"
        f"This link expires in {config.password_reset_ttl_minutes} minutes. "
        "If you did not request a password reset, you can ignore this email.\n"
    )
    safe_name = html.escape(user.name)
    safe_url = html.escape(url, quote=True)
    message.add_alternative(
        f"<p>Hi {safe_name},</p>"
        "<p>We received a request to reset your Northstar password.</p>"
        f'<p><a href="{safe_url}">Reset password</a></p>'
        f"<p>This link expires in {config.password_reset_ttl_minutes} minutes. "
        "If you did not request a password reset, you can ignore this email.</p>",
        subtype="html",
    )
    await asyncio.to_thread(smtp_send, message, config)
