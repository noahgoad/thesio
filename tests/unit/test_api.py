from fastapi.testclient import TestClient
from narrative_research_desk.api import create_app
def test_api_contract():
    client=TestClient(create_app(lambda body:{"status":"INSUFFICIENT","source_id":body["source_id"]}))
    assert client.post("/api/analyze",json={"source_id":"x","cutoff":"2026-09-15T00:00:00Z","mode":"FIXTURE"}).status_code==200
    assert client.post("/api/analyze",json={"source_id":"x","cutoff":"2026-09-15T00:00:00Z","mode":"LIVE"}).status_code==422
    assert client.get("/healthz").json()["execution"]=="NO_LIVE"
