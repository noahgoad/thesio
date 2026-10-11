"""Deterministic unit tests for causal timing, point-in-time provenance, and observation rules (C2-T02 / C2-R02)."""

import pytest
from narrative_research_desk.causal import (
    utc_time,
    to_iso_utc,
    validate_timing,
    validate_observation,
    resolve_point_in_time_revisions,
    detect_conflicts,
    build_instrument_id,
)


def test_causal_cutoff():
    """Regression coverage for the validation contract."""
    row = {
        "source_id": "x",
        "source_sha256": "a" * 64,
        "event_at": "2026-09-14T00:00:00Z",
        "published_at": "2026-09-14T00:00:01Z",
        "available_at": "2026-09-14T00:00:02Z",
        "ingested_at": "2026-09-15T00:00:00Z",
        "mode": "HISTORICAL_REPLAY",
    }
    assert validate_timing(row, "2026-09-14T00:00:03Z") == row
    with pytest.raises(ValueError, match="FUTURE_INPUT"):
        validate_timing(row, "2026-09-14T00:00:01Z")


def test_utc_time_naive_rejected():
    """Verify that timestamps lacking explicit timezone offsets are rejected with TIMEZONE_REQUIRED."""
    with pytest.raises(ValueError, match="TIMEZONE_REQUIRED"):
        utc_time("2026-09-14T10:00:00")

    with pytest.raises(ValueError, match="TIMEZONE_REQUIRED"):
        utc_time("2026-01-01 08:30:00")


def test_utc_time_dst_offsets_and_normalization():
    """Verify proper normalization of Daylight Saving Time (-04:00) and other timezone offsets to UTC."""
    # EDT summer offset (-04:00)
    dt_edt = utc_time("2026-06-15T14:30:00-04:00")
    assert dt_edt.hour == 18
    assert dt_edt.minute == 30
    assert to_iso_utc(dt_edt) == "2026-06-15T18:30:00Z"

    # EST winter offset (-05:00)
    dt_est = utc_time("2026-11-15T14:30:00-05:00")
    assert dt_est.hour == 19
    assert dt_est.minute == 30
    assert to_iso_utc(dt_est) == "2026-11-15T19:30:00Z"

    # Half-hour offset (+05:30)
    dt_ist = utc_time("2026-09-14T12:00:00+05:30")
    assert to_iso_utc(dt_ist) == "2026-09-14T06:30:00Z"


def test_validate_timing_provenance_missing():
    """Verify that omitting any required provenance field raises PROVENANCE_MISSING."""
    base_row = {
        "source_id": "src-test",
        "source_sha256": "1" * 64,
        "event_at": "2026-09-14T00:00:00Z",
        "published_at": "2026-09-14T00:00:01Z",
        "available_at": "2026-09-14T00:00:02Z",
        "ingested_at": "2026-09-15T00:00:00Z",
        "mode": "FIXTURE",
    }

    for key in base_row.keys():
        incomplete = dict(base_row)
        del incomplete[key]
        with pytest.raises(ValueError, match="PROVENANCE_MISSING"):
            validate_timing(incomplete, "2026-09-14T00:00:10Z")


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("source_id", "", "PROVENANCE_INVALID"),
        ("source_id", "   ", "PROVENANCE_INVALID"),
        ("source_sha256", "not-a-digest", "SOURCE_HASH_INVALID"),
        ("source_sha256", "a" * 63, "SOURCE_HASH_INVALID"),
    ],
)
def test_validate_timing_rejects_invalid_source_identity_and_hash(field, value, error):
    row = {
        "source_id": "source-1",
        "source_sha256": "a" * 64,
        "event_at": "2026-09-14T00:00:00Z",
        "published_at": "2026-09-14T00:00:01Z",
        "available_at": "2026-09-14T00:00:02Z",
        "ingested_at": "2026-09-15T00:00:00Z",
        "mode": "FIXTURE",
    }
    row[field] = value

    with pytest.raises(ValueError, match=error):
        validate_timing(row, "2026-09-14T00:00:10Z")


def test_validate_timing_availability_before_publication():
    """Verify that available_at prior to published_at raises AVAILABILITY_BEFORE_PUBLICATION."""
    row = {
        "source_id": "src-retro",
        "source_sha256": "3" * 64,
        "event_at": "2026-09-14T00:00:00Z",
        "published_at": "2026-09-14T00:00:10Z",
        "available_at": "2026-09-14T00:00:05Z",  # Prior to published!
        "ingested_at": "2026-09-15T00:00:00Z",
        "mode": "FIXTURE",
    }
    with pytest.raises(ValueError, match="AVAILABILITY_BEFORE_PUBLICATION"):
        validate_timing(row, "2026-09-14T00:00:20Z")


def test_validate_timing_mode_unknown():
    """Verify that unrecognized or live execution modes raise MODE_UNKNOWN."""
    row = {
        "source_id": "src-live",
        "source_sha256": "4" * 64,
        "event_at": "2026-09-14T00:00:00Z",
        "published_at": "2026-09-14T00:00:01Z",
        "available_at": "2026-09-14T00:00:02Z",
        "ingested_at": "2026-09-15T00:00:00Z",
        "mode": "LIVE_ORDERS",  # Prohibited mode
    }
    with pytest.raises(ValueError, match="MODE_UNKNOWN"):
        validate_timing(row, "2026-09-14T00:00:10Z")


def test_validate_observation_null_not_zero():
    """Verify that missing metric values remain None and are never coerced to 0 or 0.0."""
    obs = {
        "record_id": "obs-missing-capex",
        "source_id": "src-sec-nvda",
        "source_sha256": "5" * 64,
        "event_at": "2026-09-14T00:00:00Z",
        "published_at": "2026-09-14T00:00:01Z",
        "available_at": "2026-09-14T00:00:02Z",
        "ingested_at": "2026-09-15T00:00:00Z",
        "timezone": "UTC",
        "mode": "FIXTURE",
        "value": None,
        "quality_flags": ["MISSING_DATA"],
    }
    validated = validate_observation(obs, cutoff="2026-09-14T00:00:10Z")
    assert validated["value"] is None
    assert validated["value"] != 0
    assert validated["value"] != 0.0


def test_resolve_point_in_time_revisions():
    """Verify that revisions available after cutoff are excluded and pre-cutoff original is kept."""
    v1 = {
        "record_id": "obs-guidance-001",
        "base_record_id": "guidance-nvda-q3",
        "available_at": "2026-09-14T12:00:00Z",
        "value": 32.5,
    }
    v2_post_cutoff = {
        "record_id": "obs-guidance-002",
        "base_record_id": "guidance-nvda-q3",
        "available_at": "2026-09-15T08:00:00Z",
        "value": 35.0,
    }

    # At cutoff 2026-09-14T23:59:59Z, only v1 should be selected
    resolved_at_earlier_cutoff = resolve_point_in_time_revisions(
        [v1, v2_post_cutoff], cutoff="2026-09-14T23:59:59Z"
    )
    assert len(resolved_at_earlier_cutoff) == 1
    assert resolved_at_earlier_cutoff[0]["record_id"] == "obs-guidance-001"
    assert resolved_at_earlier_cutoff[0]["value"] == 32.5

    # At cutoff after v2, v2 should be selected
    resolved_at_later_cutoff = resolve_point_in_time_revisions(
        [v1, v2_post_cutoff], cutoff="2026-09-15T12:00:00Z"
    )
    assert len(resolved_at_later_cutoff) == 1
    assert resolved_at_later_cutoff[0]["record_id"] == "obs-guidance-002"
    assert resolved_at_later_cutoff[0]["value"] == 35.0


def test_detect_conflicts():
    """Verify that conflicting values for identical record_id raise IDENTITY_CONFLICT."""
    records = [
        {"record_id": "rec-100", "value": 42.0},
        {"record_id": "rec-100", "value": 99.0},
    ]
    with pytest.raises(ValueError, match="IDENTITY_CONFLICT"):
        detect_conflicts(records)

    # Valid revisions do not raise conflict
    valid_revisions = [
        {"record_id": "rec-100", "value": 42.0, "is_revision": False},
        {"record_id": "rec-100", "value": 99.0, "is_revision": True, "revision_number": 2},
    ]
    detect_conflicts(valid_revisions)  # Should succeed without error


def test_build_instrument_id():
    """Verify multi-symbol issuer isolation generates distinct instrument IDs."""
    inst_goog = build_instrument_id("NASDAQ", "EQUITY", "GOOG", "USD", "issuer_googl")
    inst_googl = build_instrument_id("NASDAQ", "EQUITY", "GOOGL", "USD", "issuer_googl")

    assert inst_goog == "NASDAQ:EQUITY:GOOG:USD:issuer_googl"
    assert inst_googl == "NASDAQ:EQUITY:GOOGL:USD:issuer_googl"
    assert inst_goog != inst_googl


def test_historical_backfill_today():
    """Verify historical data ingested today is valid as long as available_at <= cutoff."""
    row = {
        "source_id": "src-sec-backfill-2024",
        "source_sha256": "6" * 64,
        "event_at": "2024-05-10T12:00:00Z",
        "published_at": "2024-05-10T12:01:00Z",
        "available_at": "2024-05-10T12:02:00Z",
        "ingested_at": "2026-09-16T08:00:00Z",
        "mode": "HISTORICAL_BACKTEST",
    }
    # Cutoff in 2024 after available_at
    result = validate_timing(row, cutoff="2024-05-10T15:00:00Z")
    assert result["source_id"] == "src-sec-backfill-2024"
