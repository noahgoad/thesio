"""Source registry, provenance verification, and reuse tracking (C2-R01)."""

from datetime import datetime, timezone
from hashlib import sha256
import re
from typing import Any

VALID_PERMISSIONS = {"METADATA_ONLY", "LICENSED", "USER_OWNED"}
VALID_ROLES = {
    "REFERENCE_MECHANISM",
    "BENCHMARK_BASE",
    "PRIMARY_FILING",
    "USER_PORTFOLIO",
    "PRIMARY_EVIDENCE",
    "FIXTURE_DATA",
}
AWARD_DATE_CUTOFF = "2026-09-14T23:59:59Z"


def register_source(
    source_id: str,
    payload: bytes,
    origin: str,
    permission: str,
    captured_at: str,
    role: str = "PRIMARY_EVIDENCE",
    buidl_id: str | None = None,
) -> dict[str, Any]:
    """Register and compute provenance hash for an immutable source record."""
    if not source_id or not origin or not captured_at:
        raise ValueError("SOURCE_INCOMPLETE")
    if permission not in VALID_PERMISSIONS:
        raise ValueError("PERMISSION_UNKNOWN")
    if not payload:
        raise ValueError("EMPTY_SOURCE")

    digest = sha256(payload).hexdigest()
    record: dict[str, Any] = {
        "source_id": source_id,
        "sha256": digest,
        "origin": origin,
        "permission": permission,
        "captured_at": captured_at,
        "byte_length": len(payload),
        "role": role,
    }
    if buidl_id is not None:
        record["buidl_id"] = buidl_id
    return record


def verify_source_integrity(payload: bytes, expected_sha256: str) -> bool:
    """Verify that payload bytes match the recorded SHA-256 hash."""
    if not payload:
        raise ValueError("EMPTY_SOURCE")
    actual_hash = sha256(payload).hexdigest()
    if actual_hash.lower() != expected_sha256.lower():
        raise ValueError("SOURCE_HASH_MISMATCH")
    return True


def validate_buidl_id(
    source_name: str, expected_buidl: str, actual_buidl: str
) -> bool:
    """Verify project BUIDL identifier against the expected reference registration."""
    if expected_buidl != actual_buidl:
        raise ValueError(
            f"BUIDL_ID_MISMATCH: {source_name} expected {expected_buidl}, got {actual_buidl}"
        )
    return True


def validate_award_snapshot_date(
    captured_at: str, cutoff_iso: str = AWARD_DATE_CUTOFF
) -> bool:
    """Validate that reference snapshot was captured before or at the award cutoff date."""
    captured_dt = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    cutoff_dt = datetime.fromisoformat(cutoff_iso.replace("Z", "+00:00"))
    if captured_dt > cutoff_dt:
        raise ValueError("SNAPSHOT_AFTER_AWARD_DATE")
    return True


def validate_source_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Validate a single source metadata entry against C2-R01 requirements."""
    required = ("source_id", "origin", "captured_at", "sha256", "permission", "role")
    missing = [f for f in required if not entry.get(f)]
    if missing:
        raise ValueError(f"SOURCE_INCOMPLETE: missing {', '.join(missing)}")
    if entry["permission"] not in VALID_PERMISSIONS:
        raise ValueError("PERMISSION_UNKNOWN")
    digest = entry["sha256"]
    if not isinstance(digest, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", digest):
        raise ValueError("SOURCE_DIGEST_INVALID")
    if any(digest.lower() == character * 64 for character in "0123456789abcdef"):
        raise ValueError("SOURCE_DIGEST_PLACEHOLDER")
    for width in range(1, 33):
        if 64 % width == 0 and digest[:width] * (64 // width) == digest.lower():
            raise ValueError("SOURCE_DIGEST_PLACEHOLDER")

    # Reject presenting third-party reference mechanisms as an independent product result
    if entry.get("is_independent_result") and entry.get("role") in {
        "REFERENCE_MECHANISM",
        "BENCHMARK_BASE",
    }:
        raise ValueError("INDEPENDENT_RESULT_CLAIM_PROHIBITED")

    return entry


def validate_catalog(sources: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate 100% compliance of sources in release catalog against C2-R01."""
    if not sources:
        raise ValueError("EMPTY_CATALOG")

    verified: list[dict[str, Any]] = []
    for s in sources:
        verified.append(validate_source_entry(s))

    return {
        "total_sources": len(sources),
        "compliant": True,
        "verified_count": len(verified),
    }


def check_g0_gate(
    sources: list[dict[str, Any]],
    execution_mode: str = "FIXTURE",
    source_payloads: dict[str, bytes] | None = None,
) -> dict[str, Any]:
    """Check metadata, exact payload hashes, and non-live execution mode before G0."""
    catalog_result = validate_catalog(sources)
    live_modes = {"LIVE", "LIVE_EXECUTION", "ORDER_PLACING"}
    if execution_mode in live_modes:
        raise ValueError(f"GATE_G0_FAILED: live execution mode {execution_mode} prohibited in v1")

    if not isinstance(source_payloads, dict):
        raise ValueError("GATE_G0_PROVENANCE_UNVERIFIED: source payload bytes are required")
    source_ids = {source["source_id"] for source in sources}
    if set(source_payloads) != source_ids:
        raise ValueError("GATE_G0_PROVENANCE_UNVERIFIED: payload inventory does not exactly match catalog")
    for source in sources:
        payload = source_payloads[source["source_id"]]
        if not isinstance(payload, bytes):
            raise ValueError(f"GATE_G0_PROVENANCE_UNVERIFIED: payload must be bytes for {source['source_id']}")
        verify_source_integrity(payload, source["sha256"])

    return {
        "gate": "G0",
        "status": "PASS",
        "r01_sources_compliant": catalog_result["compliant"],
        "total_sources_verified": catalog_result["verified_count"],
        "payload_hashes_verified": len(source_payloads),
        "mode": execution_mode,
        "live_disabled": True,
    }
