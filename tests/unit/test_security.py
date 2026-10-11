import pytest
from narrative_research_desk.security import validate_source_url
def test_url_allowlist():
    assert validate_source_url("https://api.bitget.com/api/v3/market/instruments",{"api.bitget.com"}).startswith("https://")
    for url in ("http://127.0.0.1","https://api.bitget.com.evil.test/x","https://user:pass@api.bitget.com/x"):
        with pytest.raises(ValueError): validate_source_url(url,{"api.bitget.com"})
