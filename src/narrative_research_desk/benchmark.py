from math import isfinite
from numbers import Real
from statistics import mean, median
from typing import Any

def paired_delta(rows: list[dict[str, Any]], lower_is_better: bool, require_same_cases: bool = False) -> dict[str, Any]:
    if not isinstance(rows, list):
        raise ValueError("INVALID_PAIRED_OBSERVATIONS")
    if not rows:
        raise ValueError("NO_PAIRED_OBSERVATIONS")
    if not isinstance(lower_is_better, bool) or not isinstance(require_same_cases, bool):
        raise ValueError("INVALID_COMPARISON_MODE")
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("INVALID_PAIRED_OBSERVATION")
    ids = [row.get("case_id") for row in rows]
    if any(not isinstance(item, str) or not item.strip() for item in ids):
        raise ValueError("INVALID_PAIRED_OBSERVATION")
    if len(ids) != len(set(ids)):
        raise ValueError("DUPLICATE_CASE")
    differences = []
    for row in rows:
        if require_same_cases:
            candidate_id = row.get("candidate_case_id", row["case_id"])
            baseline_id = row.get("baseline_case_id", row["case_id"])
            if not isinstance(candidate_id, str) or not isinstance(baseline_id, str):
                raise ValueError("PAIRED_CASE_MISMATCH")
            if candidate_id != baseline_id:
                raise ValueError("PAIRED_CASE_MISMATCH")
        try:
            raw_candidate, raw_baseline = row["candidate"], row["baseline"]
        except KeyError as error:
            raise ValueError("PAIRED_VALUE_INVALID") from error
        if any(isinstance(value, bool) or not isinstance(value, Real) or not isfinite(value)
               for value in (raw_candidate, raw_baseline)):
            raise ValueError("PAIRED_VALUE_INVALID")
        candidate, baseline = float(raw_candidate), float(raw_baseline)
        if not isfinite(candidate) or not isfinite(baseline):
            raise ValueError("PAIRED_VALUE_INVALID")
        differences.append(candidate - baseline)
    delta = mean(differences)
    return {"n": len(rows), "candidate_minus_baseline": delta,
            "paired_delta_median": median(differences),
            "paired_delta_observed_range": [min(differences), max(differences)],
            "uncertainty_interpretation": "OBSERVED_SPREAD_ONLY_NOT_CONFIDENCE_INTERVAL",
            "direction_favorable": delta < 0 if lower_is_better else delta > 0,
            "statistical_support": "NOT_ESTABLISHED_BY_THIS_SUMMARY"}
