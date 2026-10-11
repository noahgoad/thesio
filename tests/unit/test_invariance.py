import pytest

from narrative_research_desk.invariance import assert_prefix_equal, assert_duplicate_invariant


def test_future_mutation_guard():
    original = [{"decision_at": "2026-09-14T00:00:00Z", "action": "hold"}]
    assert_prefix_equal(original, original + [{"decision_at": "2026-09-16T00:00:00Z", "action": "open"}], "2026-09-15T00:00:00Z")
    with pytest.raises(ValueError, match="PAST_DECISION_CHANGED"):
        assert_prefix_equal(original, [{"decision_at": "2026-09-14T00:00:00Z", "action": "open"}], "2026-09-15T00:00:00Z")


def test_revision_after_cutoff_cannot_change_past_brief():
    before = [{"decision_at": "2026-09-14T00:00:00Z", "action": "hold", "source": "filing-v1"}]
    after = before + [{"decision_at": "2026-09-16T00:00:00Z", "action": "buy", "source": "filing-v2"}]
    assert_prefix_equal(before, after, "2026-09-15T00:00:00Z")


def test_duplicate_headlines_do_not_change_deduplicated_result():
    rows = [{"headline": "Issuer raises guidance", "relevance": 0.8}, {"headline": "Rates unchanged", "relevance": 0.4}]
    assert_duplicate_invariant(rows, rows + [dict(rows[0])], key="headline")


def test_invalid_cutoff_and_missing_time_fail_closed():
    with pytest.raises(ValueError, match="TIMEZONE_REQUIRED"):
        assert_prefix_equal([], [], "2026-09-15T00:00:00")
    with pytest.raises(ValueError, match="DECISION_TIME_MISSING"):
        assert_prefix_equal([{"action": "hold"}], [], "2026-09-15T00:00:00Z")
