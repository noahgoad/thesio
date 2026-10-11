"""Issuer mapping verification, feasibility gate, and universe coverage (C2-R03)."""

import json
import re
from typing import Any

from narrative_research_desk.source_registry import validate_source_entry, verify_source_integrity

VALID_INSTRUMENT_TYPES = {"COMMON_STOCK", "ADR", "PREFERRED_STOCK", "ETF"}

MATERIAL_SOURCE_ROLES = {
    "PRIMARY_FILING",
    "PRIMARY_EVIDENCE",
    "AUDITED_FINANCIALS",
    "SEC_EDGAR_10Q",
    "SEC_EDGAR_10K",
    "SEC_EDGAR_8K",
}

NON_MATERIAL_SOURCE_ROLES = {
    "MARKETING_ONLY",
    "PRESS_RELEASE_PROMO",
    "BLOG_POST",
    "UNVERIFIED_NEWS",
    "SPONSORED_CONTENT",
}

# Canonical 8-issuer universe for AI infrastructure / semiconductor research
CANONICAL_AI_SEMICONDUCTOR_UNIVERSE: dict[str, dict[str, Any]] = {
    "NVDA": {
        "issuer_id": "NVDA",
        "legal_name": "NVIDIA Corporation",
        "cik": "0001045810",
        "ticker": "NVDA",
        "venue": "NASDAQ",
        "instrument_type": "COMMON_STOCK",
        "share_class": "COMMON",
        "sector": "Semiconductors",
        "aliases": ["NVIDIA Corp", "Nvidia"],
        "is_adr": False,
    },
    "AMD": {
        "issuer_id": "AMD",
        "legal_name": "Advanced Micro Devices, Inc.",
        "cik": "0000002488",
        "ticker": "AMD",
        "venue": "NASDAQ",
        "instrument_type": "COMMON_STOCK",
        "share_class": "COMMON",
        "sector": "Semiconductors",
        "aliases": ["Advanced Micro Devices"],
        "is_adr": False,
    },
    "AVGO": {
        "issuer_id": "AVGO",
        "legal_name": "Broadcom Inc.",
        "cik": "0001730168",
        "ticker": "AVGO",
        "venue": "NASDAQ",
        "instrument_type": "COMMON_STOCK",
        "share_class": "COMMON",
        "sector": "Semiconductors",
        "aliases": ["Broadcom Ltd", "Avago Technologies Ltd"],
        "is_adr": False,
    },
    "MU": {
        "issuer_id": "MU",
        "legal_name": "Micron Technology, Inc.",
        "cik": "0000723125",
        "ticker": "MU",
        "venue": "NASDAQ",
        "instrument_type": "COMMON_STOCK",
        "share_class": "COMMON",
        "sector": "Semiconductors",
        "aliases": ["Micron Technology"],
        "is_adr": False,
    },
    "INTC": {
        "issuer_id": "INTC",
        "legal_name": "Intel Corporation",
        "cik": "0000050863",
        "ticker": "INTC",
        "venue": "NASDAQ",
        "instrument_type": "COMMON_STOCK",
        "share_class": "COMMON",
        "sector": "Semiconductors",
        "aliases": ["Intel Corp"],
        "is_adr": False,
    },
    "MSFT": {
        "issuer_id": "MSFT",
        "legal_name": "Microsoft Corporation",
        "cik": "0000789019",
        "ticker": "MSFT",
        "venue": "NASDAQ",
        "instrument_type": "COMMON_STOCK",
        "share_class": "COMMON",
        "sector": "Systems / Cloud AI",
        "aliases": ["Microsoft Corp"],
        "is_adr": False,
    },
    "AMZN": {
        "issuer_id": "AMZN",
        "legal_name": "Amazon.com, Inc.",
        "cik": "0001018724",
        "ticker": "AMZN",
        "venue": "NASDAQ",
        "instrument_type": "COMMON_STOCK",
        "share_class": "COMMON",
        "sector": "Systems / Cloud AI",
        "aliases": ["Amazon"],
        "is_adr": False,
    },
    "GOOGL": {
        "issuer_id": "GOOGL",
        "legal_name": "Alphabet Inc.",
        "cik": "0001652044",
        "ticker": "GOOGL",
        "venue": "NASDAQ",
        "instrument_type": "COMMON_STOCK",
        "share_class": "CLASS_A",
        "sector": "Systems / Cloud AI",
        "aliases": ["Alphabet Class A", "Google Class A"],
        "is_adr": False,
    },
}

# 4 extended issuers to reach the 12-issuer ceiling
CANONICAL_EXTENDED_UNIVERSE: dict[str, dict[str, Any]] = {
    **CANONICAL_AI_SEMICONDUCTOR_UNIVERSE,
    "TSM": {
        "issuer_id": "TSM",
        "legal_name": "Taiwan Semiconductor Manufacturing Company Ltd.",
        "cik": "0001046179",
        "ticker": "TSM",
        "venue": "NYSE",
        "instrument_type": "ADR",
        "share_class": "ADR",
        "sector": "Semiconductors",
        "aliases": ["TSMC"],
        "is_adr": True,
        "adr_ratio": "1:5",
    },
    "MRVL": {
        "issuer_id": "MRVL",
        "legal_name": "Marvell Technology, Inc.",
        "cik": "0001835632",
        "ticker": "MRVL",
        "venue": "NASDAQ",
        "instrument_type": "COMMON_STOCK",
        "share_class": "COMMON",
        "sector": "Semiconductors",
        "aliases": ["Marvell"],
        "is_adr": False,
    },
    "ASML": {
        "issuer_id": "ASML",
        "legal_name": "ASML Holding N.V.",
        "cik": "0000937966",
        "ticker": "ASML",
        "venue": "NASDAQ",
        "instrument_type": "ADR",
        "share_class": "NY_REG_SHARES",
        "sector": "Semiconductors Equipment",
        "aliases": ["ASML Holding"],
        "is_adr": True,
        "adr_ratio": "1:1",
    },
    "ARM": {
        "issuer_id": "ARM",
        "legal_name": "Arm Holdings plc",
        "cik": "0001973239",
        "ticker": "ARM",
        "venue": "NASDAQ",
        "instrument_type": "ADR",
        "share_class": "ADR",
        "sector": "Semiconductors IP",
        "aliases": ["Arm Holdings"],
        "is_adr": True,
        "adr_ratio": "1:1",
    },
}

KNOWN_AMBIGUOUS_SYMBOLS = {
    "GOOG": "Ambiguous dual-class symbol (Class C non-voting vs Class A voting GOOGL). Use GOOGL or explicit share class.",
    "FB": "Historical ticker for Meta Platforms Inc; unverified alias without migration resolution.",
    "AMZN.BC": "Multi-venue unmapped synthetic symbol without verified depository mapping.",
}

SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


def issuer_coverage(issuers: list[dict], minimum: int = 8) -> bool:
    """Validate issuer readiness against supplied evidence.

    Requires at least minimum verified issuers with at least 1 verified material source.
    """
    valid = {
        row["issuer_id"]
        for row in issuers
        if row.get("mapping_verified") and row.get("material_source_count", 0) >= 1
    }
    return len(valid) >= minimum


def validate_cik(cik: str, expected_issuer_id: str | None = None) -> str:
    """Validate SEC CIK string, ensuring 10-digit format and matching expected issuer if known."""
    if not isinstance(cik, str) or not cik.strip():
        raise ValueError("INVALID_CIK: empty or non-string CIK")
    clean = cik.strip()
    if not clean.isdigit() or int(clean) == 0:
        raise ValueError(f"INVALID_CIK: '{cik}' must contain positive digits")

    padded_cik = clean.zfill(10)

    if expected_issuer_id:
        canonical = CANONICAL_EXTENDED_UNIVERSE.get(expected_issuer_id)
        if canonical and canonical["cik"] != padded_cik:
            raise ValueError(
                f"CIK_MISMATCH: {expected_issuer_id} expected CIK {canonical['cik']}, got {padded_cik}"
            )

    return padded_cik


def validate_issuer_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    """Validate an issuer mapping entry for unambiguous instrument resolution."""
    issuer_id = mapping.get("issuer_id")
    if not issuer_id or not isinstance(issuer_id, str):
        raise ValueError("ISSUER_ID_REQUIRED")

    ticker = mapping.get("ticker")
    if not ticker or not isinstance(ticker, str):
        raise ValueError("TICKER_REQUIRED")

    # Ambiguous symbol check
    if mapping.get("is_ambiguous"):
        raise ValueError(f"AMBIGUOUS_SYMBOL: {ticker} is explicitly marked ambiguous")

    if ticker in KNOWN_AMBIGUOUS_SYMBOLS and not mapping.get("disambiguated"):
        reason = KNOWN_AMBIGUOUS_SYMBOLS[ticker]
        raise ValueError(f"AMBIGUOUS_SYMBOL: {ticker} - {reason}")

    # CIK check
    raw_cik = mapping.get("cik")
    if not raw_cik:
        raise ValueError(f"INVALID_CIK: missing CIK for {issuer_id}")
    padded_cik = validate_cik(str(raw_cik), expected_issuer_id=issuer_id)

    # Instrument type check
    itype = mapping.get("instrument_type")
    if itype not in VALID_INSTRUMENT_TYPES:
        raise ValueError(f"INVALID_INSTRUMENT_TYPE: '{itype}' is not recognized")

    # ADR vs common share disambiguation
    canonical = CANONICAL_EXTENDED_UNIVERSE.get(issuer_id)
    if canonical:
        if canonical.get("is_adr"):
            if itype == "COMMON_STOCK" or not mapping.get("adr_ratio"):
                raise ValueError(
                    f"ADR_MAPPING_AMBIGUOUS: {issuer_id} is foreign depositary share; requires instrument_type='ADR' with adr_ratio"
                )
        elif itype == "ADR":
            raise ValueError(
                f"ADR_MAPPING_AMBIGUOUS: {issuer_id} is US domestic common equity, not an ADR"
            )

    # Historical name change / alias verification
    historical_name = mapping.get("historical_name")
    if historical_name:
        if not canonical:
            raise ValueError(f"NAME_CHANGE_UNVERIFIED: unrecorded issuer {issuer_id}")
        allowed_aliases = set(canonical.get("aliases", [])) | {canonical["legal_name"]}
        if historical_name not in allowed_aliases:
            raise ValueError(
                f"NAME_CHANGE_UNVERIFIED: '{historical_name}' not in verified alias history for {issuer_id}"
            )

    # Missing optional fields: preserve null without default coercion
    optional_fields = ("fiscal_year_end", "market_cap_tier", "ir_url", "currency")
    missing_fields = {f: "NOT_PROVIDED" for f in optional_fields if mapping.get(f) is None}

    validated = dict(mapping)
    validated["cik"] = padded_cik
    validated["missing_fields"] = missing_fields
    return validated


def classify_source_materiality(source: dict[str, Any]) -> str:
    """Classify whether a source provides verified material facts or marketing/PR."""
    role = source.get("role", "")
    if role in MATERIAL_SOURCE_ROLES:
        return "MATERIAL"
    if role in NON_MATERIAL_SOURCE_ROLES:
        return "MARKETING_ONLY"
    return "UNKNOWN"


def count_material_sources(sources: list[dict[str, Any]], issuer_id: str | None = None) -> int:
    """Count material sources only when captured bytes match registered provenance."""
    count = 0
    for s in sources:
        if not isinstance(s, dict) or classify_source_materiality(s) != "MATERIAL":
            continue
        if not isinstance(s.get("payload_bytes"), bytes):
            continue
        if not isinstance(s.get("issuer_id"), str) or (issuer_id is not None and s["issuer_id"] != issuer_id):
            continue
        try:
            validate_source_entry(s)
            verify_source_integrity(s["payload_bytes"], s["sha256"])
        except (KeyError, TypeError, ValueError):
            continue
        count += 1
    return count


def validate_issuer_readiness(
    issuer: dict[str, Any], sources: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Validate that an issuer has verified mapping and at least 1 verified material source."""
    validated_mapping = validate_issuer_mapping(issuer)
    issuer_id = validated_mapping["issuer_id"]

    material_count = count_material_sources(sources or [], issuer_id=issuer_id)

    if material_count < 1:
        raise ValueError(
            f"NO_MATERIAL_SOURCES: issuer '{issuer_id}' has 0 verified material sources"
        )

    if not _sec_mapping_source_bound(validated_mapping):
        raise ValueError(
            f"MAPPING_SOURCE_UNVERIFIED: issuer '{issuer_id}' requires hash-bound SEC ticker/CIK mapping bytes"
        )

    validated_mapping["material_source_count"] = material_count
    validated_mapping["mapping_verified"] = True
    return validated_mapping


def _sec_mapping_source_bound(issuer: dict[str, Any]) -> bool:
    """Bind a canonical ticker/CIK mapping to exact SEC public metadata bytes."""
    source = issuer.get("mapping_source")
    if not isinstance(source, dict) or not isinstance(source.get("payload_bytes"), bytes):
        return False
    if (
        source.get("permission") != "METADATA_ONLY"
        or source.get("role") != "SEC_ISSUER_MAPPING"
        or source.get("issuer_id") != issuer.get("issuer_id")
    ):
        return False
    try:
        validate_source_entry(source)
        verify_source_integrity(source["payload_bytes"], source["sha256"])
        document = json.loads(source["payload_bytes"])
        if not isinstance(document, dict):
            return False
        if source.get("origin") == SEC_COMPANY_TICKERS_URL:
            rows = [row for row in document.values() if isinstance(row, dict)]
            ticker_rows = [row for row in rows if row.get("ticker") == issuer.get("ticker")]
            if len(ticker_rows) != 1:
                return False
            source_cik = ticker_rows[0].get("cik_str")
            source_name = ticker_rows[0].get("title")
        else:
            canonical = CANONICAL_EXTENDED_UNIVERSE.get(issuer.get("issuer_id"))
            if canonical is None:
                return False
            expected_origin = f"https://data.sec.gov/submissions/CIK{canonical['cik']}.json"
            if source.get("origin") != expected_origin:
                return False
            source_cik = document.get("cik")
            source_name = document.get("name")
            if issuer.get("ticker") not in document.get("tickers", []):
                return False
            exchanges = document.get("exchanges", [])
            if not isinstance(exchanges, list) or not any(
                isinstance(exchange, str)
                and exchange.upper() == str(issuer.get("venue", "")).upper()
                for exchange in exchanges
            ):
                return False
        if isinstance(source_cik, bool) or source_cik is None:
            return False
        if validate_cik(str(source_cik), issuer.get("issuer_id")) != validate_cik(
            str(issuer.get("cik", "")), issuer.get("issuer_id")
        ):
            return False
        canonical = CANONICAL_EXTENDED_UNIVERSE.get(issuer.get("issuer_id"))
        if canonical is None or not isinstance(source_name, str):
            return False
        normalize = lambda value: re.sub(r"[^A-Z0-9]", "", value.upper().replace(" CORP", " CORPORATION"))
        accepted_names = {canonical["legal_name"], *canonical.get("aliases", [])}
        return normalize(source_name) in {normalize(name) for name in accepted_names}
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False


def detect_missing_fields(record: dict[str, Any]) -> dict[str, Any]:
    """Examine fundamental/metadata fields, returning null-preserving status."""
    standard_fields = [
        "issuer_id",
        "legal_name",
        "cik",
        "ticker",
        "venue",
        "instrument_type",
        "share_class",
        "sector",
        "fiscal_year_end",
        "market_cap_tier",
        "ir_url",
    ]
    missing = [f for f in standard_fields if record.get(f) is None]
    return {
        "issuer_id": record.get("issuer_id"),
        "has_missing_fields": len(missing) > 0,
        "missing_fields": missing,
        "raw_record": dict(record),
    }


def evaluate_issuer_coverage(
    issuers: list[dict[str, Any]], mode: str = "FULL_V1"
) -> dict[str, Any]:
    """Evaluate full universe coverage against C2-R03 criteria."""
    valid_ids: set[str] = set()
    insufficient: list[dict[str, Any]] = []

    for row in issuers:
        row = row if isinstance(row, dict) else {}
        issuer_id = row.get("issuer_id", "UNKNOWN")
        reasons: list[str] = []
        try:
            validate_issuer_mapping(row)
        except (TypeError, ValueError):
            reasons.append("MAPPING_NOT_VERIFIED")
        if not _sec_mapping_source_bound(row):
            reasons.append("MAPPING_SOURCE_NOT_BOUND")
        material_count = count_material_sources(row.get("material_sources", []), issuer_id=issuer_id)
        if material_count < 1:
            reasons.append("NO_MATERIAL_SOURCES")

        if not reasons and isinstance(issuer_id, str):
            valid_ids.add(issuer_id)
        else:
            insufficient.append({"issuer_id": issuer_id, "reasons": reasons or ["MAPPING_NOT_VERIFIED"]})

    minimum_required = 4 if mode in {"DEMO_NARROW", "NARROW_DEMO"} else 8
    gate_passed = len(valid_ids) >= minimum_required

    limitations: list[str] = []
    if mode == "FULL_V1" and len(valid_ids) < 8:
        limitations.append("NARROW_DEMO_CANNOT_PASS_FULL_V1_GATE")
        if len(valid_ids) >= 4:
            limitations.append("QUALIFIES_ONLY_FOR_DEMO_NARROW")

    return {
        "mode": mode,
        "minimum_required": minimum_required,
        "total_evaluated": len(issuers),
        "valid_count": len(valid_ids),
        "valid_issuer_ids": sorted(list(valid_ids)),
        "insufficient_issuers": insufficient,
        "gate_passed": gate_passed,
        "status": "PASS" if gate_passed else "INSUFFICIENT",
        "limitations": limitations,
    }


def check_g1_gate(
    issuers: list[dict[str, Any]],
    mode: str = "FULL_V1",
    timing_records: list[dict[str, Any]] | None = None,
    cutoff: str | None = None,
) -> dict[str, Any]:
    """Evaluate Gate G1 criteria (C2-R02 point-in-time provenance + C2-R03 issuer coverage)."""
    cov = evaluate_issuer_coverage(issuers, mode=mode)

    timing_valid = True
    timing_errors: list[str] = []
    if not timing_records or not cutoff:
        timing_valid = False
        timing_errors.append("TIMING_EVIDENCE_MISSING")
    else:
        from narrative_research_desk.causal import validate_timing

        expected_sources: set[tuple[str, str]] = set()
        for issuer in issuers:
            if issuer.get("issuer_id") not in cov["valid_issuer_ids"]:
                continue
            for source in issuer.get("material_sources", []):
                if (
                    not isinstance(source, dict)
                    or source.get("issuer_id") != issuer.get("issuer_id")
                    or classify_source_materiality(source) != "MATERIAL"
                    or not isinstance(source.get("payload_bytes"), bytes)
                ):
                    continue
                try:
                    validate_source_entry(source)
                    verify_source_integrity(source["payload_bytes"], source["sha256"])
                except (KeyError, TypeError, ValueError):
                    continue
                expected_sources.add((source["source_id"], source["sha256"]))

        observed_sources: list[tuple[str, str]] = []
        for rec in timing_records:
            try:
                validate_timing(rec, cutoff)
                observed_sources.append((rec["source_id"], rec["source_sha256"]))
            except Exception as exc:
                timing_valid = False
                timing_errors.append(str(exc))
        if (
            len(observed_sources) != len(set(observed_sources))
            or set(observed_sources) != expected_sources
        ):
            timing_valid = False
            timing_errors.append("TIMING_SOURCE_MISMATCH")

    gate_passed = cov["gate_passed"] and timing_valid
    limitations = list(cov["limitations"])
    if not timing_valid:
        limitations.append("TIMING_VERIFICATION_FAILED")

    return {
        "gate": "G1",
        "status": "PASS" if gate_passed else "INSUFFICIENT",
        "mode": mode,
        "coverage_passed": cov["gate_passed"],
        "timing_passed": timing_valid,
        "verified_issuer_count": cov["valid_count"],
        "minimum_required": cov["minimum_required"],
        "timing_errors": timing_errors,
        "limitations": limitations,
    }
