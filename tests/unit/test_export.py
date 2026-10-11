import pytest
from narrative_research_desk.export import export_report
def test_export_integrity():
    r={"mode":"FIXTURE","status":"INSUFFICIENT","value":None}
    assert export_report("CASE",r,["b"*64,"a"*64])["content"]==export_report("CASE",r,["a"*64,"b"*64])["content"]
    with pytest.raises(ValueError,match="EXPORT_WITHOUT_PROVENANCE"): export_report("CASE",r,[])
