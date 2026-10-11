"""Deterministic unit tests for source_registry (C2-T01 / C2-R01)."""

import pytest
from hashlib import sha256
from narrative_research_desk.source_registry import (
    register_source,
    verify_source_integrity,
    validate_buidl_id,
    validate_award_snapshot_date,
    validate_source_entry,
    validate_catalog,
    check_g0_gate,
)


def test_source_registry():
    """Regression coverage for the validation contract."""
    result = register_source(
        "fixture-1",
        b"abc",
        "fixture://case-1",
        "USER_OWNED",
        "2026-09-15T00:00:00Z",
    )
    assert (
        result["sha256"]
        == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
    assert result["byte_length"] == 3
    with pytest.raises(ValueError, match="PERMISSION_UNKNOWN"):
        register_source("x", b"a", "fixture://x", "UNKNOWN", "t")


def test_register_source_missing_fields():
    """Verify that omitting required metadata raises SOURCE_INCOMPLETE."""
    with pytest.raises(ValueError, match="SOURCE_INCOMPLETE"):
        register_source("", b"abc", "origin", "USER_OWNED", "2026-09-15T00:00:00Z")
    with pytest.raises(ValueError, match="SOURCE_INCOMPLETE"):
        register_source("src-1", b"abc", "", "USER_OWNED", "2026-09-15T00:00:00Z")
    with pytest.raises(ValueError, match="SOURCE_INCOMPLETE"):
        register_source("src-1", b"abc", "origin", "USER_OWNED", "")


def test_register_source_empty_payload():
    """Verify that registering an empty payload raises EMPTY_SOURCE."""
    with pytest.raises(ValueError, match="EMPTY_SOURCE"):
        register_source(
            "src-empty",
            b"",
            "fixture://empty",
            "USER_OWNED",
            "2026-09-15T00:00:00Z",
        )


def test_verify_source_integrity():
    """Verify SHA-256 payload integrity check detects modifications."""
    payload = b"NVIDIA 10-Q filing text"
    valid_hash = register_source(
        "nvda-filing",
        payload,
        "https://sec.gov",
        "LICENSED",
        "2026-09-14T00:00:00Z",
    )["sha256"]

    assert verify_source_integrity(payload, valid_hash) is True

    # Modified payload must raise SOURCE_HASH_MISMATCH
    altered_payload = b"NVIDIA 10-Q filing text (tampered)"
    with pytest.raises(ValueError, match="SOURCE_HASH_MISMATCH"):
        verify_source_integrity(altered_payload, valid_hash)


def test_validate_buidl_id():
    """Verify BUIDL identifier matching against verified winner records."""
    assert validate_buidl_id("Narrative Alpha", "BUIDL_S2_042", "BUIDL_S2_042") is True
    with pytest.raises(ValueError, match="BUIDL_ID_MISMATCH"):
        validate_buidl_id("Narrative Alpha", "BUIDL_S2_042", "BUIDL_WRONG_999")


def test_validate_award_snapshot_date():
    """Verify that snapshots taken after competition award cutoff are flagged."""
    # Within or before cutoff
    assert validate_award_snapshot_date("2026-09-14T12:00:00Z") is True
    # After cutoff date
    with pytest.raises(ValueError, match="SNAPSHOT_AFTER_AWARD_DATE"):
        validate_award_snapshot_date("2026-09-20T00:00:00Z")


def test_validate_source_entry_independent_result_prohibition():
    """Verify that external reference mechanisms cannot be claimed as independent results."""
    external_ref = {
        "source_id": "ref-narrative-alpha",
        "origin": "https://github.com/bitnormie01/Narrative-Alpha",
        "captured_at": "2026-09-14T00:00:00Z",
        "sha256": sha256(b"reference repository metadata").hexdigest(),
        "permission": "METADATA_ONLY",
        "role": "REFERENCE_MECHANISM",
        "is_independent_result": True,  # Prohibited claim!
    }
    with pytest.raises(ValueError, match="INDEPENDENT_RESULT_CLAIM_PROHIBITED"):
        validate_source_entry(external_ref)

    # Valid without the false claim
    external_ref["is_independent_result"] = False
    validated = validate_source_entry(external_ref)
    assert validated["source_id"] == "ref-narrative-alpha"


def test_validate_catalog_and_g0_gate():
    """Verify catalog validation and G0 gate check logic."""
    payloads = {"src-sec-nvda": b"public-filing-fixture", "src-ref-alpha": b"reference-metadata-fixture"}
    sources = [
        {
            "source_id": "src-sec-nvda",
            "origin": "https://sec.gov/edgar/data/1045810",
            "captured_at": "2026-09-14T00:00:00Z",
            "sha256": sha256(payloads["src-sec-nvda"]).hexdigest(),
            "permission": "LICENSED",
            "role": "PRIMARY_FILING",
        },
        {
            "source_id": "src-ref-alpha",
            "origin": "https://github.com/bitnormie01/Narrative-Alpha",
            "captured_at": "2026-09-14T00:00:00Z",
            "sha256": sha256(payloads["src-ref-alpha"]).hexdigest(),
            "permission": "METADATA_ONLY",
            "role": "REFERENCE_MECHANISM",
        },
    ]

    catalog_res = validate_catalog(sources)
    assert catalog_res["compliant"] is True
    assert catalog_res["verified_count"] == 2

    # Gate G0 passes in FIXTURE mode
    g0_res = check_g0_gate(sources, execution_mode="FIXTURE", source_payloads=payloads)
    assert g0_res["gate"] == "G0"
    assert g0_res["status"] == "PASS"

    # Gate G0 fails if live mode is attempted
    with pytest.raises(ValueError, match="GATE_G0_FAILED"):
        check_g0_gate(sources, execution_mode="LIVE")


def test_g0_fails_closed_without_payload_hash_verification():
    source = {
        "source_id": "metadata-only", "origin": "local://fixture", "captured_at": "2026-09-14T00:00:00Z",
        "sha256": sha256(b"source payload not supplied").hexdigest(), "permission": "USER_OWNED", "role": "FIXTURE_DATA",
    }
    with pytest.raises(ValueError, match="GATE_G0_PROVENANCE_UNVERIFIED"):
        check_g0_gate([source], execution_mode="FIXTURE")


@pytest.mark.parametrize("digest", ["a" * 64, "a1b2c3d4" * 8, "not-a-digest"])
def test_source_registry_rejects_placeholder_or_malformed_digest(digest):
    source = {
        "source_id": "bad-digest", "origin": "local://fixture", "captured_at": "2026-09-14T00:00:00Z",
        "sha256": digest, "permission": "USER_OWNED", "role": "FIXTURE_DATA",
    }
    with pytest.raises(ValueError, match="SOURCE_DIGEST_"):
        validate_source_entry(source)
