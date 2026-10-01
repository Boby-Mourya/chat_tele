from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from northstar_api.services.redaction import mask_sensitive_text


@dataclass(frozen=True)
class EducationConversationInsights:
    student_message_count: int
    topics_asked: list[str]


def _bounded_excerpt(value: str, *, max_chars: int) -> str:
    compact = " ".join(value.split())
    if not compact:
        return ""
    masked = mask_sensitive_text(compact)
    if len(masked) <= max_chars:
        return masked
    return f"{masked[: max_chars - 1].rstrip()}…"


def build_education_conversation_insights(
    student_messages: Iterable[str],
    *,
    max_topics: int = 5,
    max_chars: int = 180,
) -> EducationConversationInsights:
    """Build deterministic, privacy-bounded Student activity context.

    The original Conversation/Message rows remain the source of truth. Activity
    receives only a small set of redacted recent Student-message excerpts so the
    admin history can answer "what did this Student ask about?" without another
    LLM call or a second conversation store.
    """

    if max_topics < 1:
        raise ValueError("max_topics must be at least 1")
    if max_chars < 16:
        raise ValueError("max_chars must be at least 16")

    excerpts = [
        excerpt
        for value in student_messages
        if (excerpt := _bounded_excerpt(value, max_chars=max_chars))
    ]

    selected_reversed: list[str] = []
    seen: set[str] = set()
    for excerpt in reversed(excerpts):
        fingerprint = excerpt.casefold()
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        selected_reversed.append(excerpt)
        if len(selected_reversed) == max_topics:
            break

    return EducationConversationInsights(
        student_message_count=len(excerpts),
        topics_asked=list(reversed(selected_reversed)),
    )
