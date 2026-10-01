"""Deterministic policy and post-generation checks for grounded answers."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from northstar_api.modules.knowledge.retrieval import Evidence

_CRITICAL_WORDS = re.compile(r"\b(?:not|except|least|most|incorrect|never|only)\b", re.IGNORECASE)
_NUMERIC = re.compile(r"[-+−]?\d+(?:[.,]\d+)*(?:\s*%|\s*[A-Za-z]+)?")
_TOKENS = re.compile(r"[A-Za-z][A-Za-z0-9']{2,}")
_STOPWORDS = frozenset("the and for that this with from are was were your you can not use only about what how".split())


@dataclass(frozen=True, slots=True)
class GroundingCheck:
    allowed: bool
    reason: str | None = None


def blocked_topic(question: str, topics: Iterable[str]) -> str | None:
    normalized = question.casefold()
    for topic in topics:
        value = topic.strip().casefold()
        if value and value in normalized:
            return topic.strip()
    return None


def validate_answer(answer: str, evidence: list[Evidence]) -> GroundingCheck:
    """Reject high-risk mutations without pretending to prove semantic correctness."""
    source = "\n".join(item.text for item in evidence)
    answer_for_checks = re.sub(r"\[S\d+\]", "", answer, flags=re.IGNORECASE)
    answer_numbers = {value.casefold().replace(" ", "") for value in _NUMERIC.findall(answer_for_checks)}
    source_numbers = {value.casefold().replace(" ", "") for value in _NUMERIC.findall(source)}
    if not answer_numbers.issubset(source_numbers):
        return GroundingCheck(False, "Answer contains a number or unit absent from verified evidence")

    answer_critical = {value.casefold() for value in _CRITICAL_WORDS.findall(answer_for_checks)}
    source_critical = {value.casefold() for value in _CRITICAL_WORDS.findall(source)}
    if not answer_critical.issubset(source_critical):
        return GroundingCheck(False, "Answer contains a critical qualifier absent from verified evidence")
    answer_terms = {value.casefold() for value in _TOKENS.findall(answer_for_checks)} - _STOPWORDS
    source_terms = {value.casefold() for value in _TOKENS.findall(source)}
    if len(answer_terms) >= 5 and len(answer_terms & source_terms) / len(answer_terms) < 0.2:
        return GroundingCheck(False, "Answer has insufficient lexical support in the selected evidence")
    return GroundingCheck(True)
