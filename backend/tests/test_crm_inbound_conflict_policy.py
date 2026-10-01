from __future__ import annotations

from datetime import UTC, datetime, timedelta

from northstar_api.workers.crm_webhook_consumer import _conflict_ignore_reason


def test_crm_wins_always_allows_inbound_changes() -> None:
    platform = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)
    older_crm = platform - timedelta(hours=1)

    assert _conflict_ignore_reason("CRM_WINS", platform, older_crm) is None
    assert _conflict_ignore_reason("crm_wins", platform, None) is None


def test_platform_wins_always_protects_platform_values() -> None:
    platform = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)
    newer_crm = platform + timedelta(hours=1)

    assert _conflict_ignore_reason("PLATFORM_WINS", platform, newer_crm) == "platform_wins"
    assert _conflict_ignore_reason("platform_wins", platform, None) == "platform_wins"
    assert _conflict_ignore_reason("PLATFORM_WINS", None, newer_crm) == "platform_wins"


def test_latest_wins_rejects_only_when_platform_is_provably_newer() -> None:
    platform = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)
    older_crm = platform - timedelta(minutes=1)
    equal_crm = platform
    newer_crm = platform + timedelta(minutes=1)

    assert _conflict_ignore_reason("LATEST_WINS", platform, older_crm) == "platform_newer"
    assert _conflict_ignore_reason("LATEST_WINS", platform, equal_crm) is None
    assert _conflict_ignore_reason("LATEST_WINS", platform, newer_crm) is None


def test_latest_wins_preserves_legacy_behavior_when_timestamp_is_unavailable() -> None:
    timestamp = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)

    assert _conflict_ignore_reason("LATEST_WINS", timestamp, None) is None
    assert _conflict_ignore_reason("LATEST_WINS", None, timestamp) is None
    assert _conflict_ignore_reason("LATEST_WINS", None, None) is None


def test_unknown_policy_keeps_existing_crm_apply_behavior() -> None:
    platform = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)
    older_crm = platform - timedelta(days=1)

    assert _conflict_ignore_reason("CUSTOM_POLICY", platform, older_crm) is None
