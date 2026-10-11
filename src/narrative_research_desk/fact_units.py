"""Factual extraction, monetary unit normalization, period semantics, and accounting basis verification (C2-R04)."""

from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from typing import Any

# Supported monetary scales and multipliers
SUPPORTED_SCALES: dict[str, Decimal] = {
    "UNIT": Decimal("1"),
    "THOUSAND": Decimal("1000"),
    "MILLION": Decimal("1000000"),
    "BILLION": Decimal("1000000000"),
    "TRILLION": Decimal("1000000000000"),
}

# Standard accounting bases
SUPPORTED_BASES = {"GAAP", "NON_GAAP"}

# Standard period types
SUPPORTED_PERIOD_TYPES = {"QUARTERLY", "ANNUAL", "HALF_YEAR", "TTM"}


def extract_sec_companyfacts_facts(
    payload: bytes,
    *,
    issuer_id: str,
    expected_cik: str,
    source_id: str,
    taxonomy: str,
    concept: str,
) -> list[dict[str, Any]]:
    """Extract SEC Company Facts observations, retaining API context but never claiming text spans.

    This parses structured API values only. Filing-body text and exact textual evidence
    remain a separate requirement and are deliberately not inferred here.
    """
    if not isinstance(payload, bytes) or not payload:
        raise ValueError("PAYLOAD_INVALID: expected non-empty bytes")
    if not isinstance(issuer_id, str) or not issuer_id.strip() or not isinstance(source_id, str) or not source_id.strip():
        raise ValueError("IDENTITY_INVALID: issuer_id and source_id are required")
    if not isinstance(expected_cik, str) or not expected_cik.isdigit():
        raise ValueError("CIK_INVALID: expected numeric CIK")
    if taxonomy != "us-gaap":
        raise ValueError("TAXONOMY_UNSUPPORTED: only us-gaap facts are treated as GAAP")
    if not isinstance(concept, str) or not concept:
        raise ValueError("CONCEPT_INVALID: concept is required")
    try:
        document = json.loads(payload, parse_float=Decimal)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("PAYLOAD_INVALID: malformed JSON") from exc
    if not isinstance(document, dict):
        raise ValueError("PAYLOAD_INVALID: expected object")
    try:
        actual_cik = str(int(document.get("cik")))
        required_cik = str(int(expected_cik))
    except (TypeError, ValueError):
        raise ValueError("CIK_INVALID: payload or expected CIK is missing/invalid")
    if actual_cik != required_cik:
        raise ValueError("ISSUER_MISMATCH: Company Facts CIK does not match expected issuer")
    facts = document.get("facts")
    if not isinstance(facts, dict) or not isinstance(facts.get(taxonomy), dict):
        raise ValueError("TAXONOMY_UNSUPPORTED: requested taxonomy is absent")
    concept_data = facts[taxonomy].get(concept)
    if concept_data is None:
        return []
    if not isinstance(concept_data, dict) or not isinstance(concept_data.get("units"), dict):
        raise ValueError("FACTS_INVALID: concept units must be an object")
    digest = hashlib.sha256(payload).hexdigest()
    records: list[dict[str, Any]] = []
    for unit, observations in sorted(concept_data["units"].items()):
        if not isinstance(unit, str) or not unit or not isinstance(observations, list):
            raise ValueError("FACTS_INVALID: unit observations must be arrays")
        for observation in observations:
            if not isinstance(observation, dict) or "val" not in observation:
                raise ValueError("FACTS_INVALID: observation missing value")
            try:
                value = Decimal(str(observation["val"]))
            except (InvalidOperation, ValueError):
                raise ValueError("FACT_VALUE_INVALID: value is not decimal")
            if not value.is_finite():
                raise ValueError("FACT_VALUE_INVALID: value must be finite")
            record = {
                "fact_id": f"{issuer_id}:{concept}:{observation.get('accn', '')}:{observation.get('start', '')}:{observation.get('end', '')}:{unit}",
                "issuer_id": issuer_id,
                "metric": concept,
                "value": value,
                "unit": unit,
                "basis": "GAAP",
                "taxonomy": taxonomy,
                "source_id": source_id,
                "source_sha256": digest,
                "accession": observation.get("accn"),
                "form": observation.get("form"),
                "filed": observation.get("filed"),
                "start": observation.get("start"),
                "end": observation.get("end"),
                "fiscal_year": observation.get("fy"),
                "fiscal_period": observation.get("fp"),
                "source_span": None,
                "source_span_status": "NOT_AVAILABLE_STRUCTURED_API",
                "quality_flags": [],
            }
            records.append(record)
    return records


def normalize_usd(value: str | int | float | Decimal | None, scale: str, currency: str) -> Decimal | None:
    """Normalize a numerical monetary amount with scale into an exact USD Decimal amount.

    Validate financial units and source evidence:
    - If value is None: returns None (preserves NULL, never coerces to 0).
    - If currency != 'USD': raises ValueError('CURRENCY_CONVERSION_REQUIRED').
    - If scale is unknown: raises ValueError('SCALE_UNKNOWN').
    """
    if value is None:
        return None

    if not isinstance(currency, str) or currency.strip().upper() != "USD":
        raise ValueError("CURRENCY_CONVERSION_REQUIRED")

    norm_scale = scale.strip().upper() if isinstance(scale, str) else ""
    if norm_scale not in SUPPORTED_SCALES:
        raise ValueError("SCALE_UNKNOWN")

    multiplier = SUPPORTED_SCALES[norm_scale]

    # Clean string representation
    if isinstance(value, (int, float, Decimal)):
        str_val = str(value).strip()
    elif isinstance(value, str):
        str_val = value.strip()
    else:
        raise ValueError(f"UNSUPPORTED_VALUE_TYPE: {type(value)}")

    if not str_val:
        return None

    # Handle financial parentheses negative format, e.g. (1.2) -> -1.2
    is_paren_negative = False
    clean_val = str_val.replace(",", "").replace("$", "").replace(" ", "")
    if clean_val.startswith("(") and clean_val.endswith(")"):
        clean_val = clean_val[1:-1]
        is_paren_negative = True

    try:
        dec = Decimal(clean_val)
    except InvalidOperation as exc:
        raise ValueError(f"INVALID_NUMERICAL_VALUE: {value}") from exc

    if is_paren_negative:
        dec = -dec

    return dec * multiplier


def validate_scale(scale: str) -> str:
    """Validate and normalize monetary scale."""
    if not isinstance(scale, str):
        raise ValueError("SCALE_UNKNOWN")
    norm = scale.strip().upper()
    if norm not in SUPPORTED_SCALES:
        raise ValueError("SCALE_UNKNOWN")
    return norm


def validate_accounting_basis(basis: str) -> str:
    """Standardize and validate accounting basis (GAAP vs NON_GAAP)."""
    if not isinstance(basis, str):
        raise ValueError("INVALID_ACCOUNTING_BASIS")
    norm = basis.strip().upper().replace("-", "_")
    if norm == "NONGAAP":
        norm = "NON_GAAP"
    if norm not in SUPPORTED_BASES:
        raise ValueError(f"INVALID_ACCOUNTING_BASIS: {basis}")
    return norm


def check_basis_compatibility(basis_a: str, basis_b: str) -> bool:
    """Enforce strict separation between GAAP and NON_GAAP metrics ('không gộp GAAP với nonGAAP')."""
    norm_a = validate_accounting_basis(basis_a)
    norm_b = validate_accounting_basis(basis_b)
    if norm_a != norm_b:
        raise ValueError(f"BASIS_MISMATCH: cannot combine {norm_a} and {norm_b}")
    return True


def parse_period(period: str) -> dict[str, Any]:
    """Parse and normalize fiscal period string (e.g. 'FY2024', 'Q1 2024', '2024-Q2', 'Q3 FY2025')."""
    if not isinstance(period, str) or not period.strip():
        raise ValueError("INVALID_PERIOD_FORMAT")

    clean = period.strip().upper()

    # Pattern: FY2024, FY 2024, 2024-FY, 2024FY
    annual_m = re.search(r"\b(?:FY\s*(\d{4})|(\d{4})\s*[-_]?FY)\b", clean)
    if annual_m and not re.search(r"Q[1-4]", clean):
        year = int(annual_m.group(1) or annual_m.group(2))
        return {
            "period": f"FY{year}",
            "period_type": "ANNUAL",
            "fiscal_year": year,
            "fiscal_quarter": None,
        }

    # Preserve fiscal-year labels; fiscal quarters do not necessarily align to calendar quarters.
    fiscal_quarter_m = re.search(r"\bQ([1-4])\s*FY\s*(\d{4})\b", clean)
    if fiscal_quarter_m:
        quarter = int(fiscal_quarter_m.group(1))
        year = int(fiscal_quarter_m.group(2))
        return {
            "period": f"Q{quarter} FY{year}",
            "period_type": "QUARTERLY",
            "fiscal_year": year,
            "fiscal_quarter": quarter,
        }

    # Pattern: Q1 2024, 2024-Q1, 2024Q3
    quarter_m = re.search(r"\bQ([1-4])\s*(\d{4})\b", clean)
    if not quarter_m:
        quarter_m = re.search(r"\b(\d{4})\s*[-_]?Q([1-4])\b", clean)
        if quarter_m:
            year = int(quarter_m.group(1))
            quarter = int(quarter_m.group(2))
            return {
                "period": f"Q{quarter} {year}",
                "period_type": "QUARTERLY",
                "fiscal_year": year,
                "fiscal_quarter": quarter,
            }
    else:
        quarter = int(quarter_m.group(1))
        year = int(quarter_m.group(2))
        return {
            "period": f"Q{quarter} {year}",
            "period_type": "QUARTERLY",
            "fiscal_year": year,
            "fiscal_quarter": quarter,
        }

    # TTM (Trailing Twelve Months)
    if "TTM" in clean:
        year_m = re.search(r"\b(\d{4})\b", clean)
        year = int(year_m.group(1)) if year_m else None
        return {
            "period": f"TTM {year}" if year else "TTM",
            "period_type": "TTM",
            "fiscal_year": year,
            "fiscal_quarter": None,
        }

    raise ValueError(f"INVALID_PERIOD_FORMAT: unable to parse period '{period}'")


def validate_period_compatibility(period_a: str | dict[str, Any], period_b: str | dict[str, Any]) -> bool:
    """Enforce that yearly (ANNUAL) and quarterly (QUARTERLY) periods are never conflated without explicit normalization."""
    p_a = parse_period(period_a) if isinstance(period_a, str) else period_a
    p_b = parse_period(period_b) if isinstance(period_b, str) else period_b

    type_a = p_a.get("period_type")
    type_b = p_b.get("period_type")

    if type_a != type_b:
        raise ValueError(
            f"PERIOD_TYPE_MISMATCH: cannot directly compare {type_a} period ({p_a.get('period')}) "
            f"with {type_b} period ({p_b.get('period')})"
        )

    frame_a = "FISCAL" if "FY" in str(p_a.get("period", "")) else "CALENDAR"
    frame_b = "FISCAL" if "FY" in str(p_b.get("period", "")) else "CALENDAR"
    if frame_a != frame_b:
        raise ValueError(
            f"PERIOD_FRAME_MISMATCH: cannot directly compare {frame_a} period "
            f"({p_a.get('period')}) with {frame_b} period ({p_b.get('period')})"
        )
    return True


def verify_source_span(
    source_text: str,
    span_start: int,
    span_end: int,
    expected_snippet: str | None = None,
) -> dict[str, Any]:
    """Verify an exact, in-bounds character span against the expected source text."""
    if not isinstance(source_text, str):
        raise ValueError("INVALID_SOURCE_TEXT: expected string")

    text_len = len(source_text)
    if not isinstance(span_start, int) or not isinstance(span_end, int):
        raise ValueError("INVALID_SPAN_INDICES: span_start and span_end must be integers")

    if span_start < 0 or span_end < span_start or span_end > text_len:
        raise ValueError(
            f"SPAN_OUT_OF_BOUNDS: span [{span_start}:{span_end}] exceeds document boundaries [0:{text_len}]"
        )

    actual_snippet = source_text[span_start:span_end]

    if expected_snippet is not None:
        norm_expected = expected_snippet.strip()
        norm_actual = actual_snippet.strip()
        if norm_expected != norm_actual:
            raise ValueError(
                f"SPAN_TEXT_MISMATCH: expected snippet '{expected_snippet}' does not match span '{actual_snippet}'"
            )

    return {
        "verified": True,
        "span_start": span_start,
        "span_end": span_end,
        "extracted_text": actual_snippet,
    }


def validate_fact_record(fact: dict[str, Any], source_text: str | None = None) -> dict[str, Any]:
    """Validate a factual extraction record against unit, currency, period, and accounting basis constraints.

    Guarantees:
    - Missing or unknown numerical fields remain None (never coerced to 0).
    - Non-USD currency requires explicit conversion or raises CURRENCY_CONVERSION_REQUIRED.
    - Accounting basis is validated (GAAP vs NON_GAAP).
    - Fiscal period is parsed and validated.
    - Source spans are verified if document text is provided.
    """
    if not isinstance(fact, dict):
        raise ValueError("INVALID_FACT_PAYLOAD: expected dictionary")

    required_keys = ["fact_id", "issuer_id", "metric", "source_id", "source_sha256", "period", "basis"]
    missing = [k for k in required_keys if not fact.get(k)]
    if missing:
        raise ValueError(f"FACT_FIELD_MISSING: {', '.join(missing)}")

    if not isinstance(fact["source_sha256"], str) or not re.fullmatch(r"[0-9a-fA-F]{64}", fact["source_sha256"]):
        raise ValueError("SOURCE_SHA256_INVALID: expected 64 hexadecimal characters")

    rec = dict(fact)
    # Verification flags are derived here, never accepted from untrusted input.
    quality_flags = list(rec.get("quality_flags", []))
    quality_flags = [
        flag for flag in quality_flags
        if flag not in {"SPAN_VERIFIED", "GAAP_VERIFIED", "NON_GAAP_VERIFIED"}
    ]
    rec["quality_flags"] = quality_flags
    rec["basis"] = validate_accounting_basis(fact["basis"])
    period_info = parse_period(fact["period"])
    rec["period"] = period_info["period"]
    rec["period_type"] = period_info["period_type"]

    raw_val = fact.get("value")
    scale = fact.get("scale", "UNIT")
    currency = fact.get("currency", "USD")

    # Preserve NULL: if raw_val is None, do not coerce to 0
    if raw_val is None:
        rec["value"] = None
        rec["normalized_usd"] = None
        quality_flags = list(rec.get("quality_flags", []))
        if "UNKNOWN_VALUE" not in quality_flags:
            quality_flags.append("UNKNOWN_VALUE")
        rec["quality_flags"] = quality_flags
    else:
        norm_usd = normalize_usd(raw_val, scale=scale, currency=currency)
        rec["normalized_usd"] = norm_usd

    # Source span verification if provided
    span_start = fact.get("span_start")
    span_end = fact.get("span_end")
    if source_text is not None and span_start is not None and span_end is not None:
        expected_snip = fact.get("raw_value_text") or fact.get("source_snippet")
        verify_source_span(source_text, span_start, span_end, expected_snippet=expected_snip)
        quality_flags = list(rec.get("quality_flags", []))
        if "SPAN_VERIFIED" not in quality_flags:
            quality_flags.append("SPAN_VERIFIED")
        rec["quality_flags"] = quality_flags

    return rec


def resolve_revised_fact(
    original_fact: dict[str, Any],
    revised_fact: dict[str, Any],
    restatement_reason: str | None = None,
) -> dict[str, Any]:
    """Handle 10-K/A or 10-Q/A restatements / revisions without mutating past historical facts in-place.

    Returns a new revision record linked to the original fact via supersedes_fact_id.
    """
    if original_fact.get("fact_id") == revised_fact.get("fact_id"):
        raise ValueError("IDENTITY_CONFLICT: revised fact must have a distinct revision fact_id")

    # Enforce period and basis compatibility
    validate_period_compatibility(original_fact["period"], revised_fact["period"])
    check_basis_compatibility(original_fact["basis"], revised_fact["basis"])

    if original_fact.get("issuer_id") != revised_fact.get("issuer_id"):
        raise ValueError("ISSUER_MISMATCH: cannot revise fact across different issuers")

    new_rev = dict(revised_fact)
    new_rev["is_revised"] = True
    new_rev["supersedes_fact_id"] = original_fact["fact_id"]
    new_rev["revision_number"] = int(original_fact.get("revision_number", 1)) + 1
    new_rev["restatement_reason"] = restatement_reason or "RESTATED_FILING"

    flags = list(new_rev.get("quality_flags", []))
    if "RESTATED" not in flags:
        flags.append("RESTATED")
    new_rev["quality_flags"] = flags

    return new_rev


def compare_facts_variance(
    fact_prior: dict[str, Any],
    fact_current: dict[str, Any],
) -> dict[str, Any]:
    """Calculate variance between two facts, enforcing period type and accounting basis compatibility.

    Guarantees:
    - Never merges or compares GAAP with NON_GAAP without error.
    - Never merges or compares ANNUAL with QUARTERLY without error.
    - Preserves null if either value is None.
    """
    if fact_prior.get("issuer_id") != fact_current.get("issuer_id"):
        raise ValueError("ISSUER_MISMATCH: cannot compare facts across different issuers")

    if fact_prior.get("metric") != fact_current.get("metric"):
        raise ValueError("METRIC_MISMATCH: cannot compare differing metrics")

    # Enforce constraints
    validate_period_compatibility(fact_prior["period"], fact_current["period"])
    check_basis_compatibility(fact_prior["basis"], fact_current["basis"])

    val_prior = fact_prior.get("normalized_usd")
    val_curr = fact_current.get("normalized_usd")

    if val_prior is None or val_curr is None:
        return {
            "status": "INCOMPLETE",
            "dollar_change": None,
            "pct_change": None,
            "basis": fact_current["basis"],
            "period_type": parse_period(fact_current["period"])["period_type"],
            "reason": "MISSING_VALUE",
        }

    dollar_change = val_curr - val_prior
    pct_change = None
    if val_prior != Decimal("0"):
        pct_change = (dollar_change / abs(val_prior)) * Decimal("100")

    return {
        "status": "COMPUTED",
        "dollar_change": dollar_change,
        "pct_change": pct_change,
        "basis": fact_current["basis"],
        "period_type": parse_period(fact_current["period"])["period_type"],
        "reason": None,
    }
