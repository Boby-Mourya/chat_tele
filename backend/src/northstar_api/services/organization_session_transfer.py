"""Refresh-family transfer for an explicit, verified organization selection.

A new family is used rather than reusing the old one: a late refresh for the old
organization cannot revoke the new organization's family. No workspace grant is
created by this operation. The Redis script is atomic on the configured standalone
Redis deployment; unsupported cluster cross-slot operations fail closed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID


class OrganizationSessionError(ValueError):
    """A verified token cannot be used for the requested interactive operation."""


@dataclass(frozen=True, slots=True)
class SessionIdentity:
    user_id: UUID
    organization_id: UUID
    token_id: str
    credential_version: int


def session_identifier(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise OrganizationSessionError("Invalid session identifier")
    return value


def access_identity(claims: dict[str, Any]) -> SessionIdentity:
    """Parse only AFTER the existing JWT decoder has verified type/signature/expiry."""
    try:
        if claims.get("type") != "access":
            raise OrganizationSessionError("An access token is required")
        version = claims.get("cv", 0)
        if isinstance(version, bool) or not isinstance(version, int) or version < 0:
            raise OrganizationSessionError("Invalid credential version")
        return SessionIdentity(
            user_id=UUID(claims["sub"]),
            organization_id=UUID(claims["tid"]),
            token_id=session_identifier(claims["jti"]),
            credential_version=version,
        )
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise OrganizationSessionError("Invalid access-token identity") from exc


def refresh_identity(claims: dict[str, Any], identity: SessionIdentity) -> tuple[str, str]:
    """A cookie/body refresh proof must belong to the same identity and source org."""
    try:
        if (
            claims.get("type") != "refresh"
            or UUID(claims["sub"]) != identity.user_id
            or UUID(claims["tid"]) != identity.organization_id
            or type(claims.get("cv", 0)) is not int
            or claims.get("cv", 0) != identity.credential_version
        ):
            raise OrganizationSessionError("Refresh proof does not match the account session")
        return session_identifier(claims["fid"]), session_identifier(claims["jti"])
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise OrganizationSessionError("Invalid refresh proof; sign in again") from exc


TRANSFER_REFRESH_FAMILY = """
-- Do not mutate the winner when an old request loses a concurrent transfer.
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
if redis.call('EXISTS', KEYS[3]) ~= 0 then return 0 end
if redis.call('EXISTS', KEYS[2]) ~= 0 then return 0 end
redis.call('SET', KEYS[2], ARGV[2], 'EX', ARGV[3])
redis.call('DEL', KEYS[1])
return 1
"""


def transfer_arguments(old_family: str, old_token: str, new_family: str, new_token: str,
                       ttl_seconds: int, access_token_id: str) -> tuple[str, str, str, str, str, int]:
    values = [session_identifier(value) for value in (old_family, old_token, new_family, new_token)]
    if values[0] == values[2]:
        raise OrganizationSessionError("Organization transfer requires a new refresh family")
    if type(ttl_seconds) is not int or ttl_seconds <= 0:
        raise OrganizationSessionError("Invalid session lifetime")
    return (
        f"northstar:refresh-family:{values[0]}", f"northstar:refresh-family:{values[2]}",
        f"northstar:revoked:{session_identifier(access_token_id)}", values[1], values[3], ttl_seconds,
    )


async def transfer_family(client: Any, *, old_family: str, old_token: str,
                          new_family: str, new_token: str, ttl_seconds: int, access_token_id: str) -> bool:
    args = transfer_arguments(old_family, old_token, new_family, new_token, ttl_seconds, access_token_id)
    result = await client.eval(TRANSFER_REFRESH_FAMILY, 3, *args)
    return bool(result == 1)


REVOKE_UNDELIVERED_FAMILY = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
return redis.call('DEL', KEYS[1])
"""


async def revoke_undelivered_family(client: Any, family: str, token_id: str) -> None:
    # Compensation must not delete a different token after a collision or race.
    key = f"northstar:refresh-family:{session_identifier(family)}"
    await client.eval(REVOKE_UNDELIVERED_FAMILY, 1, key, session_identifier(token_id))
