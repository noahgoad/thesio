from copy import deepcopy
import json
import pytest
from fastapi.testclient import TestClient
from narrative_research_desk.api import create_app
from narrative_research_desk.service import ResearchWorkbenchService
from tests.unit.test_primary_workflow import capture


def test_amendments_retained_and_latest_eligible_revision_selected(tmp_path):
    reader = capture(tmp_path)
    path = tmp_path/'NVDA.json'
    document = json.loads(path.read_text())
    rows = document['facts']['us-gaap']['NetIncomeLoss']['units']['USD']
    rows.extend([{**rows[0],'val':150,'filed':'2026-06-01','form':'10-Q/A','accn':'amended'},
                 {**rows[0],'val':999,'filed':'2026-12-01','form':'10-Q/A','accn':'future-amended'}])
    path.write_text(json.dumps(document))
    from hashlib import sha256
    payload = path.read_bytes()
    manifest_path = tmp_path/'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['sources'][0].update(sha256=sha256(payload).hexdigest(),byte_length=len(payload))
    manifest_path.write_text(json.dumps(manifest))
    retained = reader.read(['NVDA'],'2026-10-11T00:00:00Z',include_history=True)
    assert any(f['accession']=='amended' for f in retained['fact_history'])
    assert not any(f['accession']=='future-amended' for f in retained['fact_history'])
    from narrative_research_desk.period_comparison import select_revisions
    selected = select_revisions(retained['fact_history'],'2026-10-11T00:00:00Z')
    assert selected[0]['value'] == '150'
    assert selected[0]['supersedes_fact_ids']
    reader.verify(retained)


def request(**changes):
    return {**dict(source_id='retained-sec-2026-09-24', mode='PUBLIC_READ', cutoff='2026-10-11T00:00:00Z',
                   question='Net income', watchlist=['NVDA']), **changes}


@pytest.mark.parametrize('question',['Quarter-on-quarter net income growth','Quarter on quarter net income growth',
                                   'Quarter-over-quarter net income growth','q/q net income growth'])
def test_api_qoq_never_returns_yoy_answer(tmp_path,question):
    capture(tmp_path)
    service = ResearchWorkbenchService([],tmp_path/'runs.db',sec_capture_dir=tmp_path)
    with TestClient(create_app(service)) as client:
        result = client.post('/api/analyze',json=request(question=question,period_request='quarterly')).json()
        assert result['brief']['status'] == 'insufficient'
        assert not result['brief']['claims']
        assert result['research_scope']['needs_confirmation']
    service.close()


def test_api_increase_question_uses_change_scope(tmp_path):
    capture(tmp_path)
    service = ResearchWorkbenchService([],tmp_path/'runs.db',sec_capture_dir=tmp_path)
    with TestClient(create_app(service)) as client:
        result = client.post('/api/analyze',json=request(question='How much did net income increase?',period_request='quarterly')).json()
        assert result['research_scope']['operation'] == 'change'
        assert result['brief']['status'] == 'insufficient'  # missing prior-year observation, not a level answer
        assert not result['brief']['claims']
    service.close()


def test_brief_reopens_and_exports_without_recomputation(tmp_path):
    capture(tmp_path)
    service = ResearchWorkbenchService([], tmp_path/'runs.db', sec_capture_dir=tmp_path)
    client = TestClient(create_app(service))
    response = client.post('/api/analyze', json=request(metric='net_income', operation='level',period_request='quarterly'))
    assert response.status_code == 200, response.text
    run = response.json()
    assert run['brief']['claims'][0]['fact_ids']
    assert client.get('/api/runs/'+run['run_id']).json()['brief'] == run['brief']
    assert client.get('/api/runs/'+run['run_id']+'/export').json()['result']['brief'] == run['brief']
    assert client.post('/api/analyze',json=request(run_id=run['run_id'],metric='net_income',operation='level',period_request='quarterly')).json() == run
    assert client.post('/api/analyze',json=request(run_id=run['run_id'],metric='revenue',operation='level')).status_code == 409
    service.close()


def test_historical_fact_pointer_is_verified(tmp_path):
    reader = capture(tmp_path)
    run = reader.read(['NVDA'], '2026-10-11T00:00:00Z', include_history=True)
    assert run['fact_history']
    reader.verify(run)
    run['fact_history'][0]['value'] = '999'
    with pytest.raises(ValueError, match='STRUCTURED_FACT_MISMATCH'):
        reader.verify(run)


def test_actual_prior_year_pointer_used_for_change_is_verified(tmp_path):
    reader = capture(tmp_path)
    document = json.loads((tmp_path/'NVDA.json').read_text())
    observations = document['facts']['us-gaap']['NetIncomeLoss']['units']['USD']
    observations.append({**observations[0],'start':'2025-01-01','end':'2025-03-31',
                         'filed':'2025-05-01','accn':'prior-year','val':100})
    payload = json.dumps(document).encode()
    (tmp_path/'NVDA.json').write_bytes(payload)
    from hashlib import sha256
    manifest = json.loads((tmp_path/'manifest.json').read_text())
    manifest['sources'][0].update(sha256=sha256(payload).hexdigest(),byte_length=len(payload))
    (tmp_path/'manifest.json').write_text(json.dumps(manifest))
    retained = reader.read(['NVDA'],'2026-10-11T00:00:00Z',include_history=True)
    from narrative_research_desk.question_scope import parse_scope
    from narrative_research_desk.research_brief import build_brief
    retained['brief'] = build_brief(parse_scope('Net income growth',['NVDA'],period_request='quarterly'),
                                   retained['fact_history'],'2026-10-11T00:00:00Z')
    assert retained['brief']['status'] == 'answered'
    prior = next(f for f in retained['fact_history'] if f['accession']=='prior-year')
    assert prior['fact_id'] in retained['brief']['claims'][0]['fact_ids']
    reader.verify(retained)
    prior['json_pointer'] = retained['facts'][0]['json_pointer']
    with pytest.raises(ValueError,match='STRUCTURED_FACT_MISMATCH'):
        reader.verify(retained)


def test_legacy_identity_and_export_are_unchanged(tmp_path):
    capture(tmp_path)
    service = ResearchWorkbenchService([], tmp_path/'runs.db', sec_capture_dir=tmp_path)
    body = request(run_id='legacy')
    retained = service.sec.read(body['watchlist'],body['cutoff'])
    legacy = {**body, **retained, 'source_sha256':retained['manifest_sha256'], 'narratives':[{'narrative_id':'old'}], 'decision':None}
    from hashlib import sha256
    inputs = {key:body[key] for key in ('source_id','cutoff','mode','question','watchlist')}
    digest = sha256(service._canonical(inputs).encode()).hexdigest()
    legacy['input_hash'] = digest
    service.repository.put_once('legacy',digest,legacy)
    service.choose('legacy',{'narrative_id':'old','note':'Old note'})
    before = service.export('legacy')['content']
    assert service.analyze(body)['input_hash'] == digest
    assert service.export('legacy')['content'] == before
    assert 'brief' not in service.read('legacy')
    service.close()
