from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import secrets
import struct
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import quote
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.config import get_settings
from northstar_api.mfa import MFARecoveryCode, MFASetting
from northstar_api.models import User
from northstar_api.password_reset import PasswordCredentialState
from northstar_api.security import verify_password

_TOTP_STEP_SECONDS = 30
_TOTP_DIGITS = 6
_TOTP_WINDOW = 1
_RECOVERY_CODE_COUNT = 10
_RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class MFAError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MFASetupMaterial:
    secret: str
    otpauth_uri: str
    recovery_codes: list[str]


def _application_secret() -> bytes:
    settings = get_settings()
    configured = settings.mfa_encryption_key
    if configured is not None:
        return configured.get_secret_value().encode("utf-8")
    # Development/test compatibility only. Production configuration requires a
    # distinct MFA_ENCRYPTION_KEY so JWT rotation cannot make TOTP secrets unreadable.
    if settings.is_production:
        raise MFAError("MFA encryption is not configured")
    return settings.jwt_secret.get_secret_value().encode("utf-8")


def _fernet() -> Fernet:
    digest = hashlib.sha256(b"northstar:mfa:secret:v1\0" + _application_secret()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _encrypt_secret(secret: str) -> bytes:
    return _fernet().encrypt(secret.encode("ascii"))


def _decrypt_secret(ciphertext: bytes) -> str:
    try:
        return _fernet().decrypt(ciphertext).decode("ascii")
    except (InvalidToken, UnicodeDecodeError) as exc:
        raise MFAError("MFA configuration is unavailable") from exc


def _normalize_recovery_code(code: str) -> str:
    return "".join(character for character in code.upper() if character.isalnum())


def _recovery_hash(user_id: UUID, code: str) -> str:
    normalized = _normalize_recovery_code(code)
    return hmac.new(
        _application_secret(),
        f"northstar:mfa:recovery:v1:{user_id}:{normalized}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _generate_recovery_codes() -> list[str]:
    values: list[str] = []
    for _ in range(_RECOVERY_CODE_COUNT):
        raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(12))
        values.append(f"{raw[:4]}-{raw[4:8]}-{raw[8:]}")
    return values


def _generate_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _secret_bytes(secret: str) -> bytes:
    padding = "=" * ((8 - len(secret) % 8) % 8)
    try:
        return base64.b32decode(secret + padding, casefold=True)
    except ValueError as exc:
        raise MFAError("MFA configuration is unavailable") from exc


def totp_code(secret: str, counter: int) -> str:
    digest = hmac.new(_secret_bytes(secret), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(binary % (10**_TOTP_DIGITS)).zfill(_TOTP_DIGITS)


def matching_totp_counter(secret: str, code: str, *, now: datetime | None = None) -> int | None:
    if len(code) != _TOTP_DIGITS or not code.isdigit():
        return None
    current = int((now or datetime.now(UTC)).timestamp()) // _TOTP_STEP_SECONDS
    for counter in range(current - _TOTP_WINDOW, current + _TOTP_WINDOW + 1):
        if counter >= 0 and hmac.compare_digest(totp_code(secret, counter), code):
            return counter
    return None


def _otpauth_uri(user: User, secret: str) -> str:
    issuer = "Northstar"
    label = quote(f"{issuer}:{user.email}", safe="")
    return (
        f"otpauth://totp/{label}?secret={quote(secret, safe='')}&issuer={quote(issuer, safe='')}"
        f"&algorithm=SHA1&digits={_TOTP_DIGITS}&period={_TOTP_STEP_SECONDS}"
    )


async def mfa_status(session: AsyncSession, user_id: UUID) -> tuple[MFASetting | None, int]:
    setting = await session.get(MFASetting, user_id)
    unused = 0
    if setting is not None and setting.enabled:
        unused = int(
            await session.scalar(
                select(func.count(MFARecoveryCode.id)).where(
                    MFARecoveryCode.user_id == user_id,
                    MFARecoveryCode.used_at.is_(None),
                )
            )
            or 0
        )
    return setting, unused


async def setup_mfa(session: AsyncSession, user_id: UUID, current_password: str) -> MFASetupMaterial:
    user = await session.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None or not user.is_active:
        raise MFAError("Account is unavailable")
    if not await asyncio.to_thread(verify_password, current_password, user.password_hash):
        raise MFAError("Current password is incorrect")

    existing = await session.get(MFASetting, user_id)
    if existing is not None and existing.enabled:
        raise MFAError("MFA is already enabled")

    secret = _generate_totp_secret()
    if existing is None:
        existing = MFASetting(user_id=user_id, secret_ciphertext=_encrypt_secret(secret), enabled=False)
        session.add(existing)
    else:
        existing.secret_ciphertext = _encrypt_secret(secret)
        existing.enabled = False
        existing.confirmed_at = None
        existing.last_counter = None
    user.mfa_enabled = False

    await session.execute(delete(MFARecoveryCode).where(MFARecoveryCode.user_id == user_id))
    recovery_codes = _generate_recovery_codes()
    session.add_all(
        MFARecoveryCode(user_id=user_id, code_hash=_recovery_hash(user_id, code))
        for code in recovery_codes
    )
    await session.flush()
    return MFASetupMaterial(
        secret=secret,
        otpauth_uri=_otpauth_uri(user, secret),
        recovery_codes=recovery_codes,
    )


async def _increment_credential_version(session: AsyncSession, user_id: UUID) -> int:
    now = datetime.now(UTC)
    state = await session.get(PasswordCredentialState, user_id)
    if state is None:
        state = PasswordCredentialState(user_id=user_id, version=1)
        session.add(state)
    else:
        state.version += 1
        state.updated_at = now
    await session.flush()
    return state.version


async def confirm_mfa(session: AsyncSession, user_id: UUID, code: str) -> int:
    setting = await session.scalar(
        select(MFASetting).where(MFASetting.user_id == user_id).with_for_update()
    )
    user = await session.scalar(select(User).where(User.id == user_id).with_for_update())
    if setting is None or user is None or setting.enabled:
        raise MFAError("MFA setup is unavailable")
    counter = matching_totp_counter(_decrypt_secret(setting.secret_ciphertext), code)
    if counter is None:
        raise MFAError("Invalid authentication code")
    now = datetime.now(UTC)
    setting.enabled = True
    setting.confirmed_at = now
    # Treat the setup confirmation as a consumed TOTP step. The same authenticator
    # code cannot then be replayed immediately to complete a login challenge.
    setting.last_counter = counter
    user.mfa_enabled = True
    return await _increment_credential_version(session, user_id)


async def consume_mfa_factor(
    session: AsyncSession,
    user_id: UUID,
    *,
    code: str | None = None,
    recovery_code: str | None = None,
) -> None:
    setting = await session.scalar(
        select(MFASetting).where(MFASetting.user_id == user_id).with_for_update()
    )
    if setting is None or not setting.enabled:
        raise MFAError("MFA is not enabled")

    now = datetime.now(UTC)
    if code is not None:
        counter = matching_totp_counter(_decrypt_secret(setting.secret_ciphertext), code, now=now)
        if counter is None or (setting.last_counter is not None and counter <= setting.last_counter):
            raise MFAError("Invalid or already used authentication code")
        setting.last_counter = counter
        await session.flush()
        return

    if recovery_code is not None:
        row = await session.scalar(
            select(MFARecoveryCode)
            .where(
                MFARecoveryCode.user_id == user_id,
                MFARecoveryCode.code_hash == _recovery_hash(user_id, recovery_code),
                MFARecoveryCode.used_at.is_(None),
            )
            .with_for_update()
        )
        if row is None:
            raise MFAError("Invalid or already used recovery code")
        row.used_at = now
        await session.flush()
        return

    raise MFAError("An MFA code is required")


async def _verify_current_password(session: AsyncSession, user_id: UUID, current_password: str) -> User:
    user = await session.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None or not user.is_active:
        raise MFAError("Account is unavailable")
    if not await asyncio.to_thread(verify_password, current_password, user.password_hash):
        raise MFAError("Current password is incorrect")
    return user


async def disable_mfa(
    session: AsyncSession,
    user_id: UUID,
    current_password: str,
    *,
    code: str | None = None,
    recovery_code: str | None = None,
) -> int:
    user = await _verify_current_password(session, user_id, current_password)
    await consume_mfa_factor(session, user_id, code=code, recovery_code=recovery_code)
    await session.execute(delete(MFARecoveryCode).where(MFARecoveryCode.user_id == user_id))
    await session.execute(delete(MFASetting).where(MFASetting.user_id == user_id))
    user.mfa_enabled = False
    return await _increment_credential_version(session, user_id)


async def regenerate_recovery_codes(
    session: AsyncSession,
    user_id: UUID,
    current_password: str,
    *,
    code: str | None = None,
    recovery_code: str | None = None,
) -> list[str]:
    await _verify_current_password(session, user_id, current_password)
    await consume_mfa_factor(session, user_id, code=code, recovery_code=recovery_code)
    await session.execute(delete(MFARecoveryCode).where(MFARecoveryCode.user_id == user_id))
    recovery_codes = _generate_recovery_codes()
    session.add_all(
        MFARecoveryCode(user_id=user_id, code_hash=_recovery_hash(user_id, value))
        for value in recovery_codes
    )
    await session.flush()
    return recovery_codes
