import pytest

from narrative_research_desk.effectiveness import classify_evidence


def test_evidence_classification():
    assert classify_evidence(True, False, 0, 20, False, False) == "NOT_EVALUATED"
    assert classify_evidence(True, True, 3, 20, True, True) == "INCONCLUSIVE"
    assert classify_evidence(True, True, 30, 20, False, True) == "NOT_SUPPORTED"
    assert classify_evidence(True, True, 30, 20, True, True) == "SUPPORTED"


@pytest.mark.parametrize("args", [
    (False, True, 30, 20, True, True),
    (True, True, 3, 20, True, True),
])
def test_small_or_unfrozen_sample_cannot_support_claim(args):
    assert classify_evidence(*args) == "INCONCLUSIVE"


def test_invalid_sample_sizes_rejected():
    with pytest.raises(ValueError, match="SAMPLE_SIZE_INVALID"):
        classify_evidence(True, True, -1, 20, True, True)


@pytest.mark.parametrize("field,args", [
    ("protocol_frozen", (1, True, 30, 20, True, True)),
    ("completed", (True, "yes", 30, 20, True, True)),
    ("favorable", (True, True, 30, 20, 1, True)),
    ("risk_pass", (True, True, 30, 20, True, "pass")),
])
def test_non_boolean_study_flags_are_rejected(field, args):
    with pytest.raises(ValueError, match=f"{field.upper()}_INVALID"):
        classify_evidence(*args)
