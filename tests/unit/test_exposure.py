import pytest
from narrative_research_desk.exposure import issuer_exposure
def test_duplicate_issuer_exposure():
    assert issuer_exposure([{"issuer_id":"NVDA","weight":.2},{"issuer_id":"NVDA","weight":.15}])["NVDA"]==pytest.approx(.35)
def test_missing_mapping_and_negative_rejected():
    with pytest.raises(ValueError,match="POSITION_MAPPING"): issuer_exposure([{"weight":.1}])
