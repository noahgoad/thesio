"""Deterministic guards against changing past research decisions."""

import json
from typing import Any

from narrative_research_desk.causal import utc_time


def _canonical(rows: list[dict[str, Any]]) -> str:
    try:
        return json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError("INVARIANCE_PAYLOAD_INVALID") from error


def assert_prefix_equal(original: list[dict[str, Any]], mutated: list[dict[str, Any]], cutoff: str) -> None:
    """Raise unless all rows available by cutoff are byte-stable as canonical JSON."""
    cutoff_time = utc_time(cutoff)

    def prefix(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        selected = []
        for row in rows:
            if not isinstance(row, dict) or "decision_at" not in row:
                raise ValueError("DECISION_TIME_MISSING")
            if utc_time(row["decision_at"]) <= cutoff_time:
                selected.append(row)
        return selected

    if _canonical(prefix(original)) != _canonical(prefix(mutated)):
        raise ValueError("PAST_DECISION_CHANGED")


def assert_duplicate_invariant(original: list[dict[str, Any]], mutated: list[dict[str, Any]], key: str) -> None:
    """Ensure duplicate records do not alter the canonical unique set, including conflicts."""
    if not key:
        raise ValueError("DEDUP_KEY_REQUIRED")

    def unique(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        found: dict[str, str] = {}
        for row in rows:
            if key not in row:
                raise ValueError("DEDUP_KEY_MISSING")
            identity = _canonical([row[key]])
            body = _canonical(row)
            if identity in found and found[identity] != body:
                raise ValueError("DEDUP_CONFLICT")
            found[identity] = body
        return [{key: json.loads(identity), "body": json.loads(body)} for identity, body in sorted(found.items())]

    if _canonical(unique(original)) != _canonical(unique(mutated)):
        raise ValueError("DEDUP_INVARIANT_CHANGED")
