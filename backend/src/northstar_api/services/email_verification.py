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
from northstar_api.email_verification import EmailVerificationState, EmailVerificationToken
from northstar_api.models import User, Workspace
from northstar_api.services.smtp import smtp_send

logger = structlog.get_logger(__name__)

# Backwards-compatible import target for the other transactional email services.
_smtp_send = smtp_send


class EmailVerificationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class IssuedVerification:
    token: str
    expires_at: datetime


def _token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def email_is_verified(session: AsyncSession, user_id: UUID) -> bool:
    state = await session.get(EmailVerificationState, user_id)
    # Legacy users intentionally have no state row and remain verified for compatibility.
    return state is None or state.verified_at is not None


async def ensure_unverified_state(session: AsyncSession, user_id: UUID) -> EmailVerificationState:
    state = await session.get(EmailVerificationState, user_id)
    if state is None:
        state = EmailVerificationState(user_id=user_id, verified_at=None)
        session.add(state)
        await session.flush()
    return state


async def issue_verification_token(
    session: AsyncSession,
    user_id: UUID,
    *,
    settings: EmailSettings | None = None,
) -> IssuedVerification:
    from northstar_api.modules.workspace.email_branding import deliver_workspace_email, render_workspace_email

    config = settings or get_email_settings()
    now = datetime.now(UTC)
    state = await ensure_unverified_state(session, user_id)
    if state.verified_at is not None:
        raise EmailVerificationError("Email address is already verified")

    await session.execute(
        update(EmailVerificationToken)
        .where(
            EmailVerificationToken.user_id == user_id,
            EmailVerificationToken.consumed_at.is_(None),
        )
        .values(consumed_at=now)
    )
    raw_token = secrets.token_urlsafe(48)
    expires_at = now + timedelta(hours=config.email_verification_ttl_hours)
    session.add(
        EmailVerificationToken(
            user_id=user_id,
            token_hash=_token_hash(raw_token),
            expires_at=expires_at,
        )
    )
    await session.flush()
    return IssuedVerification(token=raw_token, expires_at=expires_at)


async def verify_email_token(session: AsyncSession, raw_token: str) -> tuple[bool, bool]:
    token = await session.scalar(
        select(EmailVerificationToken).where(EmailVerificationToken.token_hash == _token_hash(raw_token))
    )
    if token is None:
        raise EmailVerificationError("Verification link is invalid or expired")

    state = await session.get(EmailVerificationState, token.user_id)
    if state is None:
        raise EmailVerificationError("Verification link is invalid or expired")
    if state.verified_at is not None:
        return True, True

    now = datetime.now(UTC)
    expires_at = token.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if token.consumed_at is not None or expires_at <= now:
        raise EmailVerificationError("Verification link is invalid or expired")

    state.verified_at = now
    state.updated_at = now
    await session.execute(
        update(EmailVerificationToken)
        .where(
            EmailVerificationToken.user_id == token.user_id,
            EmailVerificationToken.consumed_at.is_(None),
        )
        .values(consumed_at=now)
    )
    await session.flush()
    return True, False


def verification_url(raw_token: str, settings: EmailSettings | None = None) -> str:
    config = settings or get_email_settings()
    # Keep the bearer-style verification secret in the fragment. URL fragments
    # are handled by the browser and are not sent in the HTTP request line, so
    # reverse-proxy/access logs do not receive newly generated verification tokens.
    base = config.email_verification_frontend_url.split("#", 1)[0]
    return f"{base}#token={quote(raw_token, safe='')}"


async def send_verification_email(
    user: User,
    raw_token: str,
    *,
    workspace: Workspace | None = None,
    settings: EmailSettings | None = None,
) -> None:
    config = settings or get_email_settings()
    url = verification_url(raw_token, config)
    if workspace is not None:
        # Import lazily: workspace branding's settings store depends on the
        # authentication dependency module, which also imports this service.
        from northstar_api.modules.workspace.email_branding import (
            deliver_workspace_email,
            render_workspace_email,
        )

        rendered = render_workspace_email(
            workspace,
            "email_verification",
            context={"user_name": user.name, "user_email": user.email},
            action_url=url,
            fallback_subject="Verify your email",
            fallback_heading="Verify your email",
            fallback_body=(
                "Verify your email address to finish activating your account. "
                f"This link expires in {config.email_verification_ttl_hours} hours. "
                "If you did not create this account, you can ignore this email."
            ),
            fallback_button_label="Verify email",
        )
        await deliver_workspace_email(user.email, rendered, settings=config)
        return
    if config.email_delivery_mode == "log":
        if get_settings().is_production:
            raise EmailVerificationError("Email delivery is not configured")
        logger.info(
            "verification_email_development",
            user_id=str(user.id),
            email=user.email,
            verification_url=url,
        )
        return

    message = EmailMessage()
    message["Subject"] = "Verify your Northstar email address"
    message["From"] = f"{config.email_from_name} <{config.email_from_address}>"
    message["To"] = user.email
    message.set_content(
        f"Hi {user.name},\n\n"
        "Verify your email address to finish activating your Northstar account.\n\n"
        f"{url}\n\n"
        f"This link expires in {config.email_verification_ttl_hours} hours. "
        "If you did not create this account, you can ignore this email.\n"
    )
    safe_name = html.escape(user.name)
    safe_url = html.escape(url, quote=True)
    message.add_alternative(
        f"<p>Hi {safe_name},</p>"
        "<p>Verify your email address to finish activating your Northstar account.</p>"
        f'<p><a href="{safe_url}">Verify email address</a></p>'
        f"<p>This link expires in {config.email_verification_ttl_hours} hours. "
        "If you did not create this account, you can ignore this email.</p>",
        subtype="html",
    )
    await asyncio.to_thread(smtp_send, message, config)
