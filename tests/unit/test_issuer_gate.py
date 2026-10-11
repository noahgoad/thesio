"""Deterministic unit tests for issuer mapping, feasibility gate, and universe coverage (C2-T03 / C2-R03)."""

import json
import pytest
from narrative_research_desk.source_registry import register_source
from narrative_research_desk.issuer_gate import (
    issuer_coverage,
    validate_cik,
    validate_issuer_mapping,
    classify_source_materiality,
    count_material_sources,
    validate_issuer_readiness,
    detect_missing_fields,
    evaluate_issuer_coverage,
    check_g1_gate,
    CANONICAL_AI_SEMICONDUCTOR_UNIVERSE,
    CANONICAL_EXTENDED_UNIVERSE,
)


def _verified_source(source_id: str, issuer_id: str, role: str) -> dict:
    payload = f"{source_id} fixture bytes".encode()
    return {
        **register_source(
            source_id, payload, f"https://example.test/{source_id}", "USER_OWNED",
            "2026-09-20T00:00:00Z", role=role,
        ),
        "issuer_id": issuer_id,
        "payload_bytes": payload,
    }


def _sec_mapping_source(issuer_id: str) -> dict:
    snapshot = {
        str(index): {
            "cik_str": int(meta["cik"]),
            "ticker": meta["ticker"],
            "title": meta["legal_name"],
        }
        for index, meta in enumerate(CANONICAL_AI_SEMICONDUCTOR_UNIVERSE.values())
    }
    payload = json.dumps(snapshot, separators=(",", ":")).encode()
    mapping_source = {
        **register_source(
            "sec-company-tickers-fixture-2026-09-24", payload,
            "https://www.sec.gov/files/company_tickers.json", "METADATA_ONLY",
            "2026-09-24T00:00:00Z", role="SEC_ISSUER_MAPPING",
        ),
        "issuer_id": issuer_id,
        "payload_bytes": payload,
    }
    return mapping_source


def _source_bound_coverage_issuer(issuer_id: str) -> dict:
    return {
        **CANONICAL_AI_SEMICONDUCTOR_UNIVERSE[issuer_id],
        "mapping_source": _sec_mapping_source(issuer_id),
        "material_sources": [_verified_source(f"filing-{issuer_id}", issuer_id, "PRIMARY_FILING")],
        # These summary flags are outputs, not trusted inputs to coverage evaluation.
        "mapping_verified": True,
        "material_source_count": 1,
    }


def test_issuer_coverage():
    """Regression coverage for the validation contract."""
    rows = [
        {"issuer_id": str(i), "mapping_verified": True, "material_source_count": 1}
        for i in range(8)
    ]
    assert issuer_coverage(rows)
    assert not issuer_coverage(rows[:4])


def test_validate_cik_valid_and_invalid():
    """Verify CIK parsing, zero-padding to 10 digits, and rejection of invalid formats."""
    # Valid CIKs
    assert validate_cik("1045810") == "0001045810"
    assert validate_cik("0001045810") == "0001045810"
    assert validate_cik("2488") == "0000002488"

    # Empty or whitespace
    with pytest.raises(ValueError, match="INVALID_CIK"):
        validate_cik("")

    with pytest.raises(ValueError, match="INVALID_CIK"):
        validate_cik("   ")

    # Non-digit
    with pytest.raises(ValueError, match="INVALID_CIK"):
        validate_cik("CIK-1045810")

    # All zeros
    with pytest.raises(ValueError, match="INVALID_CIK"):
        validate_cik("0000000000")

    # CIK mismatch against expected canonical issuer
    with pytest.raises(ValueError, match="CIK_MISMATCH"):
        validate_cik("0009999999", expected_issuer_id="NVDA")


def test_ambiguous_symbol_blocked():
    """Verify that ambiguous symbols or dual-class shares without disambiguation are blocked."""
    # Explicitly marked ambiguous
    with pytest.raises(ValueError, match="AMBIGUOUS_SYMBOL"):
        validate_issuer_mapping({
            "issuer_id": "AMZN.BC",
            "ticker": "AMZN.BC",
            "cik": "0001018724",
            "instrument_type": "COMMON_STOCK",
            "is_ambiguous": True,
        })

    # Bare GOOG without disambiguated flag
    with pytest.raises(ValueError, match="AMBIGUOUS_SYMBOL"):
        validate_issuer_mapping({
            "issuer_id": "GOOG",
            "ticker": "GOOG",
            "cik": "0001652044",
            "instrument_type": "COMMON_STOCK",
            "disambiguated": False,
        })

    # Properly disambiguated GOOGL passes
    validated = validate_issuer_mapping({
        "issuer_id": "GOOGL",
        "ticker": "GOOGL",
        "cik": "0001652044",
        "instrument_type": "COMMON_STOCK",
        "share_class": "CLASS_A",
        "sector": "Systems / Cloud AI",
    })
    assert validated["ticker"] == "GOOGL"


def test_adr_vs_common_share_distinction():
    """Verify that foreign ADRs (e.g. TSM) cannot be mapped as domestic COMMON_STOCK."""
    # TSM as domestic common stock without ADR ratio raises ADR_MAPPING_AMBIGUOUS
    with pytest.raises(ValueError, match="ADR_MAPPING_AMBIGUOUS"):
        validate_issuer_mapping({
            "issuer_id": "TSM",
            "ticker": "TSM",
            "cik": "0001046179",
            "instrument_type": "COMMON_STOCK",
            "share_class": "COMMON",
        })

    # Valid ADR mapping for TSM
    adr_valid = validate_issuer_mapping({
        "issuer_id": "TSM",
        "ticker": "TSM",
        "cik": "0001046179",
        "instrument_type": "ADR",
        "share_class": "ADR",
        "adr_ratio": "1:5",
    })
    assert adr_valid["instrument_type"] == "ADR"

    # Domestic US equity (NVDA) erroneously mapped as ADR raises ADR_MAPPING_AMBIGUOUS
    with pytest.raises(ValueError, match="ADR_MAPPING_AMBIGUOUS"):
        validate_issuer_mapping({
            "issuer_id": "NVDA",
            "ticker": "NVDA",
            "cik": "0001045810",
            "instrument_type": "ADR",
            "share_class": "ADR",
        })


def test_source_materiality_and_marketing_filtering():
    """Verify that marketing/PR sources are classified as MARKETING_ONLY and excluded from material counts."""
    sources = [
        _verified_source("s1", "NVDA", "PRIMARY_FILING"),
        _verified_source("s2", "NVDA", "AUDITED_FINANCIALS"),
        {"source_id": "s3", "role": "MARKETING_ONLY"},
        {"source_id": "s4", "role": "PRESS_RELEASE_PROMO"},
        {"source_id": "s5", "role": "BLOG_POST"},
    ]

    assert classify_source_materiality(sources[0]) == "MATERIAL"
    assert classify_source_materiality(sources[1]) == "MATERIAL"
    assert classify_source_materiality(sources[2]) == "MARKETING_ONLY"
    assert classify_source_materiality(sources[3]) == "MARKETING_ONLY"
    assert classify_source_materiality(sources[4]) == "MARKETING_ONLY"

    # Count only material sources (2 out of 5)
    assert count_material_sources(sources) == 2

    # Issuer with only marketing sources raises NO_MATERIAL_SOURCES on readiness validation
    with pytest.raises(ValueError, match="NO_MATERIAL_SOURCES"):
        validate_issuer_readiness(
            {
                "issuer_id": "NVDA",
                "ticker": "NVDA",
                "cik": "0001045810",
                "instrument_type": "COMMON_STOCK",
            },
            sources=[sources[2], sources[3]],
        )


def test_material_role_without_bound_source_bytes_does_not_make_issuer_ready():
    unverified = {"source_id": "filing", "role": "PRIMARY_FILING", "issuer_id": "NVDA"}
    issuer = {"issuer_id": "NVDA", "ticker": "NVDA", "cik": "0001045810", "instrument_type": "COMMON_STOCK"}

    with pytest.raises(ValueError, match="NO_MATERIAL_SOURCES"):
        validate_issuer_readiness(issuer, sources=[unverified])


def test_material_source_requires_matching_hash_and_issuer_binding():
    source = _verified_source("filing", "NVDA", "PRIMARY_FILING")
    issuer = {**CANONICAL_AI_SEMICONDUCTOR_UNIVERSE["NVDA"], "mapping_source": _sec_mapping_source("NVDA")}
    assert validate_issuer_readiness(issuer, sources=[source])["material_source_count"] == 1

    tampered = {**source, "payload_bytes": b"different bytes"}
    cross_issuer = {**source, "issuer_id": "AMD"}
    for invalid in (tampered, cross_issuer):
        with pytest.raises(ValueError, match="NO_MATERIAL_SOURCES"):
            validate_issuer_readiness({**issuer, "mapping_source": _sec_mapping_source("NVDA")}, sources=[invalid])


def test_issuer_readiness_requires_hash_bound_sec_mapping_source():
    issuer = CANONICAL_AI_SEMICONDUCTOR_UNIVERSE["NVDA"]
    filing = _verified_source("filing-nvda-ready", "NVDA", "PRIMARY_FILING")
    with pytest.raises(ValueError, match="MAPPING_SOURCE_UNVERIFIED"):
        validate_issuer_readiness(issuer, sources=[filing])


def test_sec_submissions_metadata_binds_ticker_cik_name_and_exchange():
    payload = json.dumps({
        "cik": "1045810",
        "name": "NVIDIA CORP",
        "tickers": ["NVDA"],
        "exchanges": ["Nasdaq"],
    }, separators=(",", ":")).encode()
    source = {
        **register_source(
            "sec-submissions-nvda", payload,
            "https://data.sec.gov/submissions/CIK0001045810.json",
            "METADATA_ONLY", "2026-09-24T00:00:00Z", role="SEC_ISSUER_MAPPING",
        ),
        "issuer_id": "NVDA",
        "payload_bytes": payload,
    }
    issuer = {**CANONICAL_AI_SEMICONDUCTOR_UNIVERSE["NVDA"], "mapping_source": source}
    assert validate_issuer_readiness(
        issuer, sources=[_verified_source("nvda-material", "NVDA", "PRIMARY_FILING")]
    )["mapping_verified"] is True

    wrong_exchange = {**source, "payload_bytes": payload.replace(b"Nasdaq", b"NYSE ")}
    wrong_exchange["sha256"] = __import__("hashlib").sha256(wrong_exchange["payload_bytes"]).hexdigest()
    with pytest.raises(ValueError, match="MAPPING_SOURCE_UNVERIFIED"):
        validate_issuer_readiness(
            {**issuer, "mapping_source": wrong_exchange},
            sources=[_verified_source("nvda-material-2", "NVDA", "PRIMARY_FILING")],
        )


def test_demo_narrow_vs_full_v1_evaluation():
    """Verify that 4-issuer universe passes DEMO_NARROW but fails FULL_V1 with INSUFFICIENT."""
    demo_issuers = [
        _source_bound_coverage_issuer(issuer_id) for issuer_id in ("NVDA", "AMD", "MSFT", "GOOGL")
    ]

    # Passes DEMO_NARROW (minimum 4)
    demo_eval = evaluate_issuer_coverage(demo_issuers, mode="DEMO_NARROW")
    assert demo_eval["gate_passed"] is True
    assert demo_eval["status"] == "PASS"
    assert demo_eval["valid_count"] == 4

    # Fails FULL_V1 (minimum 8)
    full_eval = evaluate_issuer_coverage(demo_issuers, mode="FULL_V1")
    assert full_eval["gate_passed"] is False
    assert full_eval["status"] == "INSUFFICIENT"
    assert "NARROW_DEMO_CANNOT_PASS_FULL_V1_GATE" in full_eval["limitations"]


def test_coverage_evaluator_does_not_trust_self_asserted_verification_flags():
    forged = [
        {"issuer_id": f"FAKE{i}", "mapping_verified": True, "material_source_count": 1}
        for i in range(8)
    ]
    result = evaluate_issuer_coverage(forged, mode="FULL_V1")
    assert result["gate_passed"] is False
    assert result["valid_count"] == 0


def test_coverage_evaluator_requires_hash_bound_sec_mapping_and_material_bytes():
    issuer_ids = list(CANONICAL_AI_SEMICONDUCTOR_UNIVERSE)
    complete = [_source_bound_coverage_issuer(issuer_id) for issuer_id in issuer_ids]
    assert evaluate_issuer_coverage(complete, mode="FULL_V1")["gate_passed"] is True

    missing_mapping = [dict(row) for row in complete]
    missing_mapping[0]["mapping_source"] = {**missing_mapping[0]["mapping_source"], "payload_bytes": b"tampered"}
    assert evaluate_issuer_coverage(missing_mapping, mode="FULL_V1")["gate_passed"] is False

    missing_filing = [dict(row) for row in complete]
    missing_filing[0]["material_sources"] = []
    assert evaluate_issuer_coverage(missing_filing, mode="FULL_V1")["gate_passed"] is False


def test_changed_name_and_alias_verification():
    """Verify that historical name changes must be verified against recorded corporate alias history."""
    # Verified historical alias for AVGO ("Broadcom Ltd")
    valid_alias = validate_issuer_mapping({
        "issuer_id": "AVGO",
        "ticker": "AVGO",
        "cik": "0001730168",
        "instrument_type": "COMMON_STOCK",
        "share_class": "COMMON",
        "historical_name": "Broadcom Ltd",
    })
    assert valid_alias["historical_name"] == "Broadcom Ltd"

    # Unverified historical name for AVGO raises NAME_CHANGE_UNVERIFIED
    with pytest.raises(ValueError, match="NAME_CHANGE_UNVERIFIED"):
        validate_issuer_mapping({
            "issuer_id": "AVGO",
            "ticker": "AVGO",
            "cik": "0001730168",
            "instrument_type": "COMMON_STOCK",
            "share_class": "COMMON",
            "historical_name": "Fabricated Unrecorded Name",
        })


def test_detect_missing_fields_preserves_null():
    """Verify that missing fields remain null/None without coercion to 0, 0.0, or default strings."""
    record = {
        "issuer_id": "NVDA",
        "legal_name": "NVIDIA Corporation",
        "cik": "0001045810",
        "ticker": "NVDA",
        "venue": "NASDAQ",
        "instrument_type": "COMMON_STOCK",
        "share_class": "COMMON",
        "sector": "Semiconductors",
        "fiscal_year_end": None,
        "market_cap_tier": None,
        "ir_url": None,
    }

    result = detect_missing_fields(record)
    assert result["has_missing_fields"] is True
    assert "fiscal_year_end" in result["missing_fields"]
    assert "market_cap_tier" in result["missing_fields"]
    assert "ir_url" in result["missing_fields"]
    # Raw record preserved with intact None values
    assert result["raw_record"]["fiscal_year_end"] is None
    assert result["raw_record"]["fiscal_year_end"] != 0


def test_canonical_ai_semiconductor_universe_integrity():
    """Verify that all 8 default canonical issuers are complete, valid, and meet coverage criteria."""
    assert len(CANONICAL_AI_SEMICONDUCTOR_UNIVERSE) == 8
    expected_ids = {"NVDA", "AMD", "AVGO", "MU", "INTC", "MSFT", "AMZN", "GOOGL"}
    assert set(CANONICAL_AI_SEMICONDUCTOR_UNIVERSE.keys()) == expected_ids

    validated_list = []
    for issuer_id, meta in CANONICAL_AI_SEMICONDUCTOR_UNIVERSE.items():
        val = validate_issuer_mapping(meta)
        assert val["issuer_id"] == issuer_id
        assert len(val["cik"]) == 10
        validated_list.append({"issuer_id": issuer_id, "mapping_verified": True, "material_source_count": 1})

    # Full 8 issuers satisfy issuer_coverage
    assert issuer_coverage(validated_list, minimum=8) is True
    eval_res = evaluate_issuer_coverage(
        [_source_bound_coverage_issuer(issuer_id) for issuer_id in expected_ids], mode="FULL_V1"
    )
    assert eval_res["gate_passed"] is True
    assert eval_res["status"] == "PASS"


def test_check_g1_gate_with_provenance():
    """Verify check_g1_gate combining universe coverage and causal timing."""
    issuers = [
        _source_bound_coverage_issuer(issuer_id) for issuer_id in CANONICAL_AI_SEMICONDUCTOR_UNIVERSE
    ]
    valid_timing = []
    for issuer in issuers:
        source = issuer["material_sources"][0]
        valid_timing.append({
            "source_id": source["source_id"],
            "source_sha256": source["sha256"],
            "event_at": "2026-09-14T00:00:00Z",
            "published_at": "2026-09-14T00:00:01Z",
            "available_at": "2026-09-14T00:00:02Z",
            "ingested_at": "2026-09-15T00:00:00Z",
            "mode": "FIXTURE",
        })

    # Gate G1 passes with valid coverage and timing
    g1_pass = check_g1_gate(
        issuers,
        mode="FULL_V1",
        timing_records=valid_timing,
        cutoff="2026-09-14T12:00:00Z",
    )
    assert g1_pass["status"] == "PASS"
    assert g1_pass["coverage_passed"] is True
    assert g1_pass["timing_passed"] is True

    # Gate G1 fails if timing violates cutoff (future input)
    g1_fail_timing = check_g1_gate(
        issuers,
        mode="FULL_V1",
        timing_records=valid_timing,
        cutoff="2026-09-14T00:00:01Z",  # Cutoff before available_at!
    )
    assert g1_fail_timing["status"] == "INSUFFICIENT"
    assert g1_fail_timing["timing_passed"] is False
    assert "TIMING_VERIFICATION_FAILED" in g1_fail_timing["limitations"]


@pytest.mark.parametrize(
    ("timing_records", "cutoff"),
    [
        (None, "2026-09-14T12:00:00Z"),
        ([{}], None),
        ([], "2026-09-14T12:00:00Z"),
        (None, None),
    ],
)
def test_check_g1_gate_fails_closed_without_complete_timing_evidence(timing_records, cutoff):
    issuers = [
        _source_bound_coverage_issuer(issuer_id)
        for issuer_id in CANONICAL_AI_SEMICONDUCTOR_UNIVERSE
    ]

    result = check_g1_gate(
        issuers, mode="FULL_V1", timing_records=timing_records, cutoff=cutoff
    )

    assert result["status"] == "INSUFFICIENT"
    assert result["coverage_passed"] is True
    assert result["timing_passed"] is False
    assert "TIMING_VERIFICATION_FAILED" in result["limitations"]


def test_check_g1_gate_rejects_timing_for_unrelated_source():
    issuers = [
        _source_bound_coverage_issuer(issuer_id)
        for issuer_id in CANONICAL_AI_SEMICONDUCTOR_UNIVERSE
    ]
    unrelated_timing = [{
        "source_id": "not-an-issuer-source",
        "source_sha256": "f" * 64,
        "event_at": "2026-09-14T00:00:00Z",
        "published_at": "2026-09-14T00:00:01Z",
        "available_at": "2026-09-14T00:00:02Z",
        "ingested_at": "2026-09-15T00:00:00Z",
        "mode": "FIXTURE",
    }]

    result = check_g1_gate(
        issuers, mode="FULL_V1", timing_records=unrelated_timing,
        cutoff="2026-09-14T12:00:00Z",
    )

    assert result["status"] == "INSUFFICIENT"
    assert result["timing_passed"] is False
    assert "TIMING_SOURCE_MISMATCH" in result["timing_errors"]
