"""User-supplied evidence is exact text, never synthetic market or human evidence."""
import json
from hashlib import sha256

import pytest
from fastapi.testclient import TestClient

from narrative_research_desk.api import create_app
from narrative_research_desk.service import ResearchWorkbenchService


def supplied():
    return {"text": "Revenue grew. Margins fell. <script>alert(1)</script>",
            "origin": "My notes.txt", "permission": "USER_OWNED",
            "evidence": [{"stance": "support", "quote": "Revenue grew.", "issuer_id": "NVDA"},
                         {"stance": "challenge", "quote": "Margins fell.", "issuer_id": "NVDA"}]}


def test_explicit_unicode_quote_offset_preserves_selected_occurrence(tmp_path):
    text = '🙂 Revenue was $12.5 billion. Revenue was $12.5 billion.'
    quote = 'Revenue was $12.5 billion.'
    start = text.rindex(quote)
    service = ResearchWorkbenchService([],tmp_path/'offset.db')
    client = TestClient(create_app(service))
    response = client.post('/api/sources',json=dict(text=text,origin='Own notes',permission='USER_OWNED',
        evidence=[dict(stance='support',issuer_id='NVDA',quote=quote,start=start)]))
    assert response.status_code == 201, response.text
    retained = service.repository.get_source(response.json()['source_id'])
    assert retained['evidence'][0]['start'] == start
    assert retained['text'][start:retained['evidence'][0]['end']] == quote
    service.close()


def test_ingest_analyze_restart_decide_export_and_replay(tmp_path):
    path = tmp_path / "runs.sqlite3"
    service = ResearchWorkbenchService([], path)
    client = TestClient(create_app(service))
    source = client.post("/api/sources", json=supplied())
    assert source.status_code == 201
    metadata = source.json()
    assert metadata["sha256"] == sha256(supplied()["text"].encode()).hexdigest()
    assert metadata["mode"] == "USER_SUPPLIED"
    service.close()
    service = ResearchWorkbenchService([], path)
    client = TestClient(create_app(service))
    request = {"source_id": metadata["source_id"], "mode": "USER_SUPPLIED",
               "cutoff": metadata["available_at"], "question": "Is growth durable?",
               "watchlist": ["NVDA"], "run_id": "user-run"}
    response = client.post("/api/analyze", json=request)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "COMPLETE"
    assert result["baskets"] == []
    assert {item["stance"] for item in result["citations"]} == {"support", "challenge"}
    assert all(item["span_verified"] for item in result["citations"])
    assert result["source_document"]["text"] == supplied()["text"]
    assert result["provenance_status"] == "USER_ASSERTED_ORIGIN"
    assert result["unknowns"] and result["search_coverage"] == "SUPPLIED_DOCUMENT_ONLY"
    assert client.post("/api/analyze", json=request).json() == result
    assert client.post("/api/analyze", json={**request, "question": "Changed"}).status_code == 409
    decision = {"narrative_id": "support", "note": "Check durability."}
    assert client.post("/api/runs/user-run/decision", json=decision).status_code == 200
    service.close()
    service = ResearchWorkbenchService([], path)
    client = TestClient(create_app(service))
    export = client.get("/api/runs/user-run/export")
    exported = export.json()["result"]
    assert exported["decision"] == decision
    assert exported["source_document"]["text"] == supplied()["text"]
    assert export.headers["x-content-sha256"] == sha256(export.content).hexdigest()
    service.close()


@pytest.mark.parametrize("change,detail", [
    ({"text": " "}, "SOURCE_CONTENT_MISSING"),
    ({"text": "abc\u0000def"}, "SOURCE_TEXT_INVALID"),
    ({"permission": "METADATA_ONLY"}, "SOURCE_CONTENT_PERMISSION_REQUIRED"),
    ({"evidence": [{"stance": "support", "quote": "invented", "issuer_id": "NVDA"}]}, "CITATION_SPAN_INVALID"),
])
def test_ingestion_rejects_invalid_content_and_unsupported_quotes(change, detail):
    service = ResearchWorkbenchService([])
    client = TestClient(create_app(service))
    response = client.post("/api/sources", json={**supplied(), **change})
    assert response.status_code == 422
    assert response.json()["detail"] == detail
    service.close()


def test_missing_challenge_and_watchlist_coverage_remain_insufficient():
    service = ResearchWorkbenchService([])
    client = TestClient(create_app(service))
    body = supplied()
    body["evidence"] = body["evidence"][:1]
    source = client.post("/api/sources", json=body).json()
    request = {"source_id": source["source_id"], "mode": "USER_SUPPLIED", "cutoff": source["available_at"],
               "question": "Growth?", "watchlist": ["NVDA"]}
    result = client.post("/api/analyze", json=request).json()
    assert result["status"] == "INSUFFICIENT"
    assert result["evidence_status"]["challenge"] == "NOT_FOUND"
    assert client.post("/api/analyze", json={**request, "watchlist": ["AMD"]}).status_code == 422
    assert client.post("/api/analyze", json={**request, "cutoff": "2000-01-01T00:00:00Z"}).status_code == 422
    assert client.post("/api/analyze", json={**request, "mode": "FIXTURE"}).status_code == 422
    service.close()
