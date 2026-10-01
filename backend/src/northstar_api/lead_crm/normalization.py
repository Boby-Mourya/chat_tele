from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NormalizedIdentity:
    email: str | None
    phone: str | None


def normalize_email(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().casefold()
    return normalized or None


def normalize_phone(value: str | None) -> str | None:
    """Return a deterministic phone key without guessing a country code.

    Provider/channel adapters should supply E.164 whenever they know the country.
    This helper intentionally does not invent geographic context.
    """
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    leading_plus = raw.startswith("+")
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None
    return f"+{digits}" if leading_plus else digits


def normalize_identity(email: str | None, phone: str | None) -> NormalizedIdentity:
    return NormalizedIdentity(email=normalize_email(email), phone=normalize_phone(phone))
