from __future__ import annotations

import pytest

from northstar_api.services.education_conversation_insights import (
    build_education_conversation_insights,
)


def test_education_conversation_insights_are_redacted_bounded_recent_and_deduplicated() -> None:
    result = build_education_conversation_insights(
        [
            "  What is the CPA exam structure?  ",
            "Please email me at student@example.com about exam dates.",
            "What is the CPA exam structure?",
            "How does financial reporting consolidation work?",
            "My password is super-secret-value, can you help me log in?",
            "What are the audit evidence requirements?",
            "Explain revenue recognition for a contract with multiple performance obligations and variable consideration across reporting periods.",
        ],
        max_topics=5,
        max_chars=80,
    )

    assert result.student_message_count == 7
    assert len(result.topics_asked) == 5
    assert result.topics_asked[0] == "What is the CPA exam structure?"
    assert "[REDACTED]" in result.topics_asked[2]
    assert "super-secret-value" not in " ".join(result.topics_asked)
    assert all(len(topic) <= 80 for topic in result.topics_asked)
    assert result.topics_asked[-1].endswith("…")


def test_education_conversation_insights_mask_email_and_ignore_blank_messages() -> None:
    result = build_education_conversation_insights(
        ["", "   ", "Send notes to learner@example.com please"],
    )

    assert result.student_message_count == 1
    assert result.topics_asked == ["Send notes to [REDACTED_EMAIL] please"]


def test_education_conversation_insights_validate_bounds() -> None:
    with pytest.raises(ValueError, match="max_topics"):
        build_education_conversation_insights(["Question"], max_topics=0)
    with pytest.raises(ValueError, match="max_chars"):
        build_education_conversation_insights(["Question"], max_chars=8)
