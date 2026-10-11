"""Deterministic unit tests for factual extraction, unit normalization, period semantics, and basis verification (C2-T04 / C2-R04)."""

from decimal import Decimal
import json
import pytest

from narrative_research_desk.fact_units import (
    normalize_usd,
    validate_scale,
    validate_accounting_basis,
    check_basis_compatibility,
    parse_period,
    validate_period_compatibility,
    verify_source_span,
    validate_fact_record,
    resolve_revised_fact,
    compare_facts_variance,
    SUPPORTED_SCALES,
    extract_sec_companyfacts_facts,
)


def test_financial_units():
    """Regression coverage for the validation contract."""
    assert normalize_usd("1.2", "BILLION", "USD") == Decimal("1200000000")
    assert normalize_usd(None, "MILLION", "USD") is None


def test_sec_companyfacts_extraction_preserves_filing_context_without_forging_text_spans():
    payload = json.dumps({
        "cik": 1045810,
        "entityName": "NVIDIA CORP",
        "facts": {"us-gaap": {"RevenueFromContractWithCustomerExcludingAssessedTax": {
            "label": "Revenue from Contract with Customer, Excluding Assessed Tax",
            "units": {"USD": [{
                "start": "2025-01-27", "end": "2025-04-27", "val": 44100000000,
                "accn": "0001045810-25-000052", "fy": 2026, "fp": "Q1",
                "form": "10-Q", "filed": "2025-05-20",
            }]},
        }}}}, separators=(",", ":")).encode()

    records = extract_sec_companyfacts_facts(
        payload, issuer_id="NVDA", expected_cik="0001045810",
        source_id="sec-companyfacts-NVDA", taxonomy="us-gaap",
        concept="RevenueFromContractWithCustomerExcludingAssessedTax",
    )
    assert len(records) == 1
    record = records[0]
    assert record["value"] == Decimal("44100000000")
    assert record["unit"] == "USD"
    assert record["basis"] == "GAAP"
    assert record["form"] == "10-Q"
    assert record["accession"] == "0001045810-25-000052"
    assert record["source_span"] is None
    assert record["source_span_status"] == "NOT_AVAILABLE_STRUCTURED_API"
    assert "SPAN_VERIFIED" not in record["quality_flags"]


def test_sec_companyfacts_extraction_blocks_wrong_issuer_and_non_gaap_claims():
    payload = json.dumps({"cik": 1045810, "entityName": "NVIDIA CORP", "facts": {}}).encode()
    with pytest.raises(ValueError, match="ISSUER_MISMATCH"):
        extract_sec_companyfacts_facts(
            payload, issuer_id="NVDA", expected_cik="0000002488", source_id="src",
            taxonomy="us-gaap", concept="Revenue",
        )
    with pytest.raises(ValueError, match="TAXONOMY_UNSUPPORTED"):
        extract_sec_companyfacts_facts(
            payload, issuer_id="NVDA", expected_cik="0001045810", source_id="src",
            taxonomy="custom", concept="AdjustedRevenue",
        )


def test_sec_companyfacts_extraction_preserves_json_decimal_digits_exactly():
    payload = (b'{"cik":1045810,"entityName":"NVIDIA CORP","facts":{"us-gaap":{"EarningsPerShareBasic":'
               b'{"units":{"USD/shares":[{"val":0.1234567890123456789,"accn":"a",'
               b'"form":"10-Q","filed":"2025-05-20","end":"2025-04-27"}]}}}}}')

    records = extract_sec_companyfacts_facts(
        payload, issuer_id="NVDA", expected_cik="0001045810", source_id="src",
        taxonomy="us-gaap", concept="EarningsPerShareBasic",
    )

    assert records[0]["value"] == Decimal("0.1234567890123456789")


def test_sec_companyfacts_distinguishes_quarter_and_year_to_date_rows_with_same_end():
    base = {
        "end": "2025-07-27", "accn": "0001045810-25-000105", "form": "10-Q",
        "filed": "2025-08-27", "fy": 2026, "fp": "Q2",
    }
    payload = json.dumps({
        "cik": 1045810,
        "facts": {"us-gaap": {"RevenueFromContractWithCustomerExcludingAssessedTax": {
            "units": {"USD": [
                {**base, "start": "2025-04-28", "val": 46743000000},
                {**base, "start": "2025-01-27", "val": 90734000000},
            ]},
        }}},
    }).encode()

    records = extract_sec_companyfacts_facts(
        payload, issuer_id="NVDA", expected_cik="0001045810",
        source_id="sec-companyfacts-NVDA", taxonomy="us-gaap",
        concept="RevenueFromContractWithCustomerExcludingAssessedTax",
    )

    assert len(records) == 2
    assert len({record["fact_id"] for record in records}) == 2
    assert {record["start"] for record in records} == {"2025-04-28", "2025-01-27"}


def test_scale_multipliers():
    """Verify all supported scale multipliers and scale validation."""
    assert normalize_usd("100", "UNIT", "USD") == Decimal("100")
    assert normalize_usd("150", "THOUSAND", "USD") == Decimal("150000")
    assert normalize_usd("25.5", "MILLION", "USD") == Decimal("25500000")
    assert normalize_usd("3.75", "BILLION", "USD") == Decimal("3750000000")
    assert normalize_usd("1.5", "TRILLION", "USD") == Decimal("1500000000000")

    # Unknown scale raises SCALE_UNKNOWN
    with pytest.raises(ValueError, match="SCALE_UNKNOWN"):
        normalize_usd("100", "MEGA", "USD")

    with pytest.raises(ValueError, match="SCALE_UNKNOWN"):
        validate_scale("UNKNOWN_SCALE")


def test_negative_values_and_formatting():
    """Verify negative monetary values, accounting parentheses, and commas."""
    # Negative strings
    assert normalize_usd("-450.5", "MILLION", "USD") == Decimal("-450500000")
    assert normalize_usd("-1.2", "BILLION", "USD") == Decimal("-1200000000")

    # Accounting parentheses notation (1,610) -> -1610
    assert normalize_usd("(1,610)", "MILLION", "USD") == Decimal("-1610000000")
    assert normalize_usd("(0.45)", "BILLION", "USD") == Decimal("-450000000")

    # Comma formatting
    assert normalize_usd("1,200.50", "MILLION", "USD") == Decimal("1200500000")
    assert normalize_usd("$30.04", "BILLION", "USD") == Decimal("30040000000")

    # Empty string returns None
    assert normalize_usd("   ", "MILLION", "USD") is None


def test_currency_conversion_required():
    """Verify that non-USD currencies fail-closed with CURRENCY_CONVERSION_REQUIRED."""
    with pytest.raises(ValueError, match="CURRENCY_CONVERSION_REQUIRED"):
        normalize_usd("100", "MILLION", "EUR")

    with pytest.raises(ValueError, match="CURRENCY_CONVERSION_REQUIRED"):
        normalize_usd("50", "BILLION", "JPY")

    with pytest.raises(ValueError, match="CURRENCY_CONVERSION_REQUIRED"):
        normalize_usd("25", "MILLION", "TWD")


def test_accounting_basis_separation():
    """Verify GAAP vs NON_GAAP distinction and basis incompatibility."""
    assert validate_accounting_basis("GAAP") == "GAAP"
    assert validate_accounting_basis("NON_GAAP") == "NON_GAAP"
    assert validate_accounting_basis("nonGAAP") == "NON_GAAP"
    assert validate_accounting_basis("non_gaap") == "NON_GAAP"

    # Invalid basis
    with pytest.raises(ValueError, match="INVALID_ACCOUNTING_BASIS"):
        validate_accounting_basis("ADJUSTED_HYBRID")

    # Compatibility checks
    assert check_basis_compatibility("GAAP", "GAAP") is True
    assert check_basis_compatibility("NON_GAAP", "NON_GAAP") is True

    # Mixing GAAP and NON_GAAP raises BASIS_MISMATCH
    with pytest.raises(ValueError, match="BASIS_MISMATCH"):
        check_basis_compatibility("GAAP", "NON_GAAP")

    with pytest.raises(ValueError, match="BASIS_MISMATCH"):
        check_basis_compatibility("NON_GAAP", "GAAP")


def test_period_parsing_and_compatibility():
    """Verify period parsing and that Annual and Quarterly periods cannot be conflated."""
    # Annual parsing
    p_ann1 = parse_period("FY2024")
    assert p_ann1["period_type"] == "ANNUAL"
    assert p_ann1["fiscal_year"] == 2024
    assert p_ann1["fiscal_quarter"] is None

    p_ann2 = parse_period("2024-FY")
    assert p_ann2["period_type"] == "ANNUAL"
    assert p_ann2["fiscal_year"] == 2024

    # Quarterly parsing
    p_q1 = parse_period("Q2 2024")
    assert p_q1["period_type"] == "QUARTERLY"
    assert p_q1["fiscal_year"] == 2024
    assert p_q1["fiscal_quarter"] == 2

    p_q2 = parse_period("2025-Q1")
    assert p_q2["period_type"] == "QUARTERLY"
    assert p_q2["fiscal_year"] == 2025
    assert p_q2["fiscal_quarter"] == 1

    p_fiscal_q = parse_period("Q2 FY2025")
    assert p_fiscal_q["period"] == "Q2 FY2025"
    assert p_fiscal_q["period_type"] == "QUARTERLY"
    assert p_fiscal_q["fiscal_year"] == 2025
    assert p_fiscal_q["fiscal_quarter"] == 2

    # Compatibility
    assert validate_period_compatibility("FY2024", "FY2025") is True
    assert validate_period_compatibility("Q1 2024", "Q2 2024") is True

    # Yearly vs Quarterly mismatch raises PERIOD_TYPE_MISMATCH
    with pytest.raises(ValueError, match="PERIOD_TYPE_MISMATCH"):
        validate_period_compatibility("FY2024", "Q1 2024")

    with pytest.raises(ValueError, match="PERIOD_TYPE_MISMATCH"):
        validate_period_compatibility("Q3 2025", "FY2025")

    with pytest.raises(ValueError, match="PERIOD_FRAME_MISMATCH"):
        validate_period_compatibility("Q2 FY2025", "Q2 2025")


def test_source_span_verification():
    """Verify document span offset boundaries and snippet matching."""
    doc_text = "NVIDIA reported revenue for the second quarter of fiscal 2025 of $30.04 billion, up 122% from a year ago."

    # Valid span
    res = verify_source_span(doc_text, 65, 79, "$30.04 billion")
    assert res["verified"] is True
    assert res["extracted_text"] == "$30.04 billion"

    # Out of bounds raises SPAN_OUT_OF_BOUNDS
    with pytest.raises(ValueError, match="SPAN_OUT_OF_BOUNDS"):
        verify_source_span(doc_text, 200, 250)

    with pytest.raises(ValueError, match="SPAN_OUT_OF_BOUNDS"):
        verify_source_span(doc_text, -5, 10)

    # Inverted span
    with pytest.raises(ValueError, match="SPAN_OUT_OF_BOUNDS"):
        verify_source_span(doc_text, 50, 40)

    # Text mismatch raises SPAN_TEXT_MISMATCH
    with pytest.raises(ValueError, match="SPAN_TEXT_MISMATCH"):
        verify_source_span(doc_text, 65, 79, "$99.99 billion")

    # A larger span containing the expected quote is not an exact source span.
    with pytest.raises(ValueError, match="SPAN_TEXT_MISMATCH"):
        verify_source_span(doc_text, 0, len(doc_text), "$30.04 billion")


def test_fact_record_validation_and_null_preservation():
    """Verify fact record validation, required keys, and null preservation."""
    valid_record = {
        "fact_id": "fact-001",
        "issuer_id": "NVDA",
        "metric": "REVENUE",
        "value": "30.04",
        "scale": "BILLION",
        "currency": "USD",
        "period": "Q2 2025",
        "basis": "GAAP",
        "source_id": "src-nvda-10q",
        "source_sha256": "4b680c2fdb8beff731a5418b763ec78d4c965b746ea5d63f03a6d4eeff00bbfb",
    }
    validated = validate_fact_record(valid_record)
    assert validated["normalized_usd"] == Decimal("30040000000")
    assert validated["basis"] == "GAAP"
    assert validated["period_type"] == "QUARTERLY"

    # Null value MUST NOT be coerced to 0
    null_record = dict(valid_record)
    null_record["value"] = None
    validated_null = validate_fact_record(null_record)
    assert validated_null["value"] is None
    assert validated_null["normalized_usd"] is None
    assert "UNKNOWN_VALUE" in validated_null["quality_flags"]
    assert validated_null["value"] != 0
    assert validated_null["value"] != 0.0

    # Missing required field raises FACT_FIELD_MISSING
    invalid_record = dict(valid_record)
    del invalid_record["source_id"]
    with pytest.raises(ValueError, match="FACT_FIELD_MISSING"):
        validate_fact_record(invalid_record)

    malformed_digest = dict(valid_record, source_sha256="not-a-sha256")
    with pytest.raises(ValueError, match="SOURCE_SHA256_INVALID"):
        validate_fact_record(malformed_digest)


def test_fact_validation_does_not_trust_incoming_verification_flags():
    source_text = "NVIDIA reported revenue for the second quarter of fiscal 2025 of $30.04 billion, up 122%."
    fact = {
        "fact_id": "fact-untrusted-flags",
        "issuer_id": "NVDA",
        "metric": "REVENUE",
        "value": "30.04",
        "scale": "BILLION",
        "currency": "USD",
        "period": "Q2 FY2025",
        "basis": "GAAP",
        "source_id": "sec-filing",
        "source_sha256": "a" * 64,
        "raw_value_text": "$30.04 billion",
        "span_start": 65,
        "span_end": 79,
        "quality_flags": ["SPAN_VERIFIED", "GAAP_VERIFIED", "NON_GAAP_VERIFIED"],
    }

    without_bytes = validate_fact_record(fact)
    assert "SPAN_VERIFIED" not in without_bytes["quality_flags"]
    assert "GAAP_VERIFIED" not in without_bytes["quality_flags"]
    assert "NON_GAAP_VERIFIED" not in without_bytes["quality_flags"]

    with_bytes = validate_fact_record(fact, source_text=source_text)
    assert "SPAN_VERIFIED" in with_bytes["quality_flags"]
    assert "GAAP_VERIFIED" not in with_bytes["quality_flags"]
    assert "NON_GAAP_VERIFIED" not in with_bytes["quality_flags"]


def test_revised_filing_resolution():
    """Verify that restated filings create new revision records without mutating original facts."""
    orig = {
        "fact_id": "fact-orig",
        "issuer_id": "NVDA",
        "metric": "REVENUE",
        "value": "60.9",
        "scale": "BILLION",
        "currency": "USD",
        "period": "FY2024",
        "basis": "GAAP",
        "revision_number": 1,
    }
    rev = {
        "fact_id": "fact-rev",
        "issuer_id": "NVDA",
        "metric": "REVENUE",
        "value": "60.8",
        "scale": "BILLION",
        "currency": "USD",
        "period": "FY2024",
        "basis": "GAAP",
    }

    resolved = resolve_revised_fact(orig, rev, restatement_reason="10-K/A revision")
    assert resolved["is_revised"] is True
    assert resolved["supersedes_fact_id"] == "fact-orig"
    assert resolved["revision_number"] == 2
    assert resolved["restatement_reason"] == "10-K/A revision"

    # Original record remains completely untouched
    assert orig["value"] == "60.9"
    assert orig.get("is_revised") is None

    # Same fact_id raises IDENTITY_CONFLICT
    with pytest.raises(ValueError, match="IDENTITY_CONFLICT"):
        resolve_revised_fact(orig, orig)


def test_compare_facts_variance():
    """Verify period variance calculation enforcing basis and cadence compatibility."""
    fact_prior = {
        "issuer_id": "AMD",
        "metric": "REVENUE",
        "normalized_usd": Decimal("5359000000"),
        "period": "Q1 2024",
        "basis": "GAAP",
    }
    fact_curr = {
        "issuer_id": "AMD",
        "metric": "REVENUE",
        "normalized_usd": Decimal("5835000000"),
        "period": "Q2 2024",
        "basis": "GAAP",
    }

    res = compare_facts_variance(fact_prior, fact_curr)
    assert res["status"] == "COMPUTED"
    assert res["dollar_change"] == Decimal("476000000")
    assert res["pct_change"] > Decimal("8.8")

    # Incompatible basis raises BASIS_MISMATCH
    fact_nongapp = dict(fact_curr)
    fact_nongapp["basis"] = "NON_GAAP"
    with pytest.raises(ValueError, match="BASIS_MISMATCH"):
        compare_facts_variance(fact_prior, fact_nongapp)

    # Incompatible period cadence raises PERIOD_TYPE_MISMATCH
    fact_annual = dict(fact_curr)
    fact_annual["period"] = "FY2024"
    with pytest.raises(ValueError, match="PERIOD_TYPE_MISMATCH"):
        compare_facts_variance(fact_prior, fact_annual)

    # Missing value yields INCOMPLETE with dollar_change None
    fact_null = dict(fact_curr)
    fact_null["normalized_usd"] = None
    res_null = compare_facts_variance(fact_prior, fact_null)
    assert res_null["status"] == "INCOMPLETE"
    assert res_null["dollar_change"] is None
