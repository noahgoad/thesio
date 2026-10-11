"""Source-span and counterevidence contracts for C2-R05."""

import pytest

from narrative_research_desk.citations import verify_citation, verify_span


def test_source_span():
    text = "Revenue rose; guidance fell."
    assert verify_span(text, 0, 12, "Revenue rose")
    assert not verify_span(text, 0, 12, "Profit rose")


@pytest.mark.parametrize(
    ("start", "end", "quote"),
    [(-1, 2, "Re"), (0, 99, "Revenue"), (13, 27, "guidance rose"), (0, 13, "Revenue fell;")],
)
def test_source_span_fails_closed_for_invalid_bounds_or_quote(start, end, quote):
    assert not verify_span("Revenue rose; guidance fell.", start, end, quote)


def test_citation_requires_registered_source_matching_hash_and_existing_counterfact():
    sources = {"s1": {"sha256": "a" * 64, "text": "Revenue rose; guidance fell."}}
    facts = {"f1"}
    valid = {"source_id": "s1", "source_sha256": "a" * 64, "start": 0, "end": 12, "quote": "Revenue rose", "counter_fact_id": "f1"}
    assert verify_citation(valid, sources, facts)["counter_fact_status"] == "FOUND"
    invalid = dict(valid, source_id="invented")
    with pytest.raises(ValueError, match="CITATION_SOURCE_NOT_FOUND"):
        verify_citation(invalid, sources, facts)
    missing = dict(valid, counter_fact_id="missing")
    assert verify_citation(missing, sources, facts)["counter_fact_status"] == "NOT_FOUND"
