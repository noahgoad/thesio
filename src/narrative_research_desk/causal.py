"""Causal timing, point-in-time provenance, and observation schema validation (C2-R02)."""

from datetime import datetime, timezone
import re
from typing import Any

VALID_MODES = {
    "FIXTURE",
    "PUBLIC_READ",
    "HISTORICAL_BACKTEST",
    "HISTORICAL_REPLAY",
    "FORWARD_PAPER",
    "USER_TEST",
}

REQUIRED_PROVENANCE = (
    "source_id",
    "source_sha256",
    "event_at",
    "published_at",
    "available_at",
    "ingested_at",
    "mode",
)


def utc_time(value: str) -> datetime:
    """Parse ISO timestamp, require explicit timezone info, and convert to UTC datetime."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("INVALID_TIMESTAMP: empty or non-string timestamp")
    clean = value.strip().replace("Z", "+00:00").replace("z", "+00:00")
    try:
        parsed = datetime.fromisoformat(clean)
    except Exception as exc:
        raise ValueError(f"INVALID_TIMESTAMP: {value}") from exc
    if parsed.tzinfo is None:
        raise ValueError("TIMEZONE_REQUIRED")
    return parsed.astimezone(timezone.utc)


def to_iso_utc(value: datetime | str) -> str:
    """Normalize any datetime or ISO string to standardized UTC ISO-8601 format (YYYY-MM-DDTHH:MM:SSZ)."""
    dt = utc_time(value) if isinstance(value, str) else value.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _validate_source_identity(record: dict[str, Any]) -> None:
    if not isinstance(record.get("source_id"), str) or not record["source_id"].strip():
        raise ValueError("PROVENANCE_INVALID: source_id")
    digest = record.get("source_sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", digest):
        raise ValueError("SOURCE_HASH_INVALID")


def validate_timing(row: dict[str, Any], cutoff: str) -> dict[str, Any]:
    """Validate point-in-time provenance and causal ordering against cutoff timestamp.

    Validate timing and point-in-time source boundaries.
    """
    if any(row.get(key) is None for key in REQUIRED_PROVENANCE):
        raise ValueError("PROVENANCE_MISSING")
    _validate_source_identity(row)

    # Verify event_at and ingested_at have timezone information as well
    utc_time(row["event_at"])
    utc_time(row["ingested_at"])

    published = utc_time(row["published_at"])
    available = utc_time(row["available_at"])
    cutoff_dt = utc_time(cutoff)

    if available < published:
        raise ValueError("AVAILABILITY_BEFORE_PUBLICATION")
    if available > cutoff_dt:
        raise ValueError("FUTURE_INPUT")
    if row["mode"] not in VALID_MODES:
        raise ValueError("MODE_UNKNOWN")

    return dict(row)


def validate_observation(
    record: dict[str, Any], cutoff: str | None = None
) -> dict[str, Any]:
    """Validate full observation record according to C2-R02 schema and rules."""
    # Provenance check
    if any(record.get(key) is None for key in REQUIRED_PROVENANCE):
        raise ValueError("PROVENANCE_MISSING")
    _validate_source_identity(record)

    # Timezone metadata check
    if not record.get("timezone"):
        raise ValueError("TIMEZONE_REQUIRED")

    # If cutoff is provided, validate point-in-time constraint
    if cutoff is not None:
        validate_timing(record, cutoff)
    else:
        # Validate internal temporal causality and mode
        published = utc_time(record["published_at"])
        available = utc_time(record["available_at"])
        if available < published:
            raise ValueError("AVAILABILITY_BEFORE_PUBLICATION")
        if record["mode"] not in VALID_MODES:
            raise ValueError("MODE_UNKNOWN")

    # Null value non-coercion check: value must remain None if missing (not 0 or 0.0)
    # Return dictionary with intact null values
    return dict(record)


def resolve_point_in_time_revisions(
    records: list[dict[str, Any]], cutoff: str
) -> list[dict[str, Any]]:
    """Select point-in-time valid records as of cutoff, preventing post-cutoff revisions from leaking.

    If an amended record's available_at > cutoff, it is ignored and the pre-cutoff version is kept.
    """
    cutoff_dt = utc_time(cutoff)
    grouped: dict[str, list[dict[str, Any]]] = {}

    for r in records:
        group_key = (
            r.get("base_record_id")
            or r.get("record_id")
            or f"{r.get('issuer_id')}:{r.get('category')}"
        )
        grouped.setdefault(group_key, []).append(r)

    resolved: list[dict[str, Any]] = []
    for _key, group in grouped.items():
        # Filter eligible records where available_at <= cutoff
        eligible = [r for r in group if utc_time(r["available_at"]) <= cutoff_dt]
        if not eligible:
            continue
        # Pick the latest available eligible revision
        latest = max(eligible, key=lambda r: utc_time(r["available_at"]))
        resolved.append(latest)

    return resolved


def detect_conflicts(records: list[dict[str, Any]]) -> None:
    """Detect un-annotated conflicting records for the same record identity."""
    seen: dict[str, Any] = {}
    for r in records:
        rid = r.get("record_id")
        if not rid:
            continue
        val = r.get("value")
        # Check if record is marked as revision
        is_rev = (
            r.get("is_revision")
            or r.get("revision_number") is not None
            or r.get("supersedes")
        )
        if rid in seen and not is_rev:
            prev_val = seen[rid]
            if prev_val != val:
                raise ValueError(
                    f"IDENTITY_CONFLICT: Conflicting payload for record_id '{rid}'"
                )
        seen[rid] = val


def build_instrument_id(
    venue: str, category: str, symbol: str, currency: str, issuer_id: str
) -> str:
    """Build standardized instrument identifier ensuring multi-symbol issuer isolation."""
    if not all([venue, category, symbol, currency, issuer_id]):
        raise ValueError("INSTRUMENT_SPECIFICATION_INCOMPLETE")
    return f"{venue.upper()}:{category.upper()}:{symbol.upper()}:{currency.upper()}:{issuer_id}"
