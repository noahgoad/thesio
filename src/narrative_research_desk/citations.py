"""Traceable source-span citations and explicit counterevidence states."""

from __future__ import annotations

from typing import Any


def verify_span(document: str, start: int, end: int, quoted: str) -> bool:
    """Return true only for an exact, in-bounds Unicode span from the immutable source text."""
    return (
        isinstance(document, str)
        and isinstance(start, int)
        and not isinstance(start, bool)
        and isinstance(end, int)
        and not isinstance(end, bool)
        and isinstance(quoted, str)
        and 0 <= start < end <= len(document)
        and document[start:end] == quoted
    )


def verify_citation(citation: dict[str, Any], sources: dict[str, dict[str, Any]], fact_ids: set[str]) -> dict[str, Any]:
    """Validate a citation against registered source content; never invent a missing counterfact."""
    if not isinstance(citation, dict):
        raise ValueError("CITATION_INVALID")
    source_id = citation.get("source_id")
    source = sources.get(source_id)
    if source is None:
        raise ValueError("CITATION_SOURCE_NOT_FOUND")
    if citation.get("source_sha256") != source.get("sha256"):
        raise ValueError("CITATION_SOURCE_HASH_MISMATCH")
    if not verify_span(source.get("text"), citation.get("start"), citation.get("end"), citation.get("quote")):
        raise ValueError("CITATION_SPAN_INVALID")
    counter_fact_id = citation.get("counter_fact_id")
    return {
        "source_id": source_id,
        "span_verified": True,
        "counter_fact_id": counter_fact_id,
        "counter_fact_status": "FOUND" if counter_fact_id in fact_ids else "NOT_FOUND",
    }


def verify_material_claims(claims: list[dict[str, Any]], sources: dict[str, dict[str, Any]], fact_ids: set[str]) -> dict[str, Any]:
    """Require every declared material claim to have a valid, replayable source span."""
    verified: list[dict[str, Any]] = []
    for claim in claims:
        if not isinstance(claim, dict):
            raise ValueError("CLAIM_INVALID")
        if claim.get("material"):
            if not isinstance(claim.get("citation"), dict):
                raise ValueError("MATERIAL_CLAIM_CITATION_REQUIRED")
            verified.append({"claim_id": claim.get("claim_id"), **verify_citation(claim["citation"], sources, fact_ids)})
    return {"status": "PASS", "material_claims_verified": len(verified), "citations": verified}
