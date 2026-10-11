import pytest

from narrative_research_desk.ranking import research_score


def test_conflicts_reduce_research_rank():
    assert research_score(1, 1, 1, 1) == pytest.approx(0.7)
    assert research_score(1, 1, 1, 0) == pytest.approx(1)


def test_out_of_range_score_is_rejected():
    with pytest.raises(ValueError, match="SCORE_RANGE"):
        research_score(1.1, 1, 1, 0)
