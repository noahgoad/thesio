import pytest
from narrative_research_desk.basket import research_basket
def test_basket_cap_and_cash():
    result=research_basket({"NVDA":10,"AMD":0})
    assert result["NVDA"]==0.25 and result["CASH"]==0.75
def test_budget_range_and_all_negative():
    with pytest.raises(ValueError, match="BUDGET_RANGE"): research_basket({}, 1.1)
    assert research_basket({"NVDA":-1}) == {"CASH":1.0}
