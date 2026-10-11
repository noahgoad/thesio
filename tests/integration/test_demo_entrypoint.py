"""The local demo must load only the declared synthetic source."""

from fastapi.testclient import TestClient


def test_demo_entrypoint_can_analyze_registered_fixture():
    from narrative_research_desk.demo import app

    client = TestClient(app)
    page = client.get("/")
    assert page.status_code == 200
    response = client.post("/api/analyze", json={
        "run_id": "demo-entrypoint-test",
        "question": "What supports growth and what invalidates it?",
        "watchlist": ["NVDA", "AMD"],
        "source_id": "fixture-ai-capex-001",
        "cutoff": "2026-09-15T00:00:00Z",
        "mode": "FIXTURE",
    })
    assert response.status_code == 200
    assert response.json()["mode"] == "FIXTURE"
