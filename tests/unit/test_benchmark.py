import pytest
from narrative_research_desk.benchmark import paired_delta

def test_paired_comparison():
    result=paired_delta([{"case_id":"1","candidate":8,"baseline":10},{"case_id":"2","candidate":7,"baseline":9}],True)
    assert result["candidate_minus_baseline"]==-2
    assert result["statistical_support"]=="NOT_ESTABLISHED_BY_THIS_SUMMARY"
    with pytest.raises(ValueError,match="NO_PAIRED_OBSERVATIONS"):paired_delta([],True)

def test_duplicate_cases_and_missing_pairs_are_rejected():
    with pytest.raises(ValueError,match="DUPLICATE_CASE"):paired_delta([{"case_id":"x","candidate":1,"baseline":2},{"case_id":"x","candidate":2,"baseline":3}],True)

@pytest.mark.parametrize("value", [True, "1", None, float("nan"), float("inf"), -float("inf")])
def test_paired_comparison_rejects_non_finite_or_non_numeric_values(value):
    with pytest.raises(ValueError, match="PAIRED_VALUE_INVALID"):
        paired_delta([{"case_id": "1", "candidate": value, "baseline": 0}], True)

@pytest.mark.parametrize("rows", [None, {}, [None], [{}], [{"case_id": " ", "candidate": 1, "baseline": 0}]])
def test_paired_comparison_rejects_malformed_observations(rows):
    with pytest.raises(ValueError, match="INVALID_PAIRED_OBSERVATION"):
        paired_delta(rows, True)

def test_paired_comparison_rejects_invalid_mode_flags():
    with pytest.raises(ValueError, match="INVALID_COMPARISON_MODE"):
        paired_delta([{"case_id": "1", "candidate": 1, "baseline": 0}], 1)
    with pytest.raises(ValueError, match="INVALID_COMPARISON_MODE"):
        paired_delta([{"case_id": "1", "candidate": 1, "baseline": 0}], True, require_same_cases=1)
