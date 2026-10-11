import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from narrative_research_desk.api import create_app
from narrative_research_desk.service import ResearchWorkbenchService

FIXTURE = json.loads((Path(__file__).parents[1]/'fixtures/research/R09.json').read_text())


def setup(tmp_path):
    service = ResearchWorkbenchService([FIXTURE],tmp_path/'runs.db')
    run = service.analyze(dict(source_id='fixture-ai-capex-001',mode='FIXTURE',cutoff='2026-09-15T00:00:00Z',
                               question='Revenue',watchlist=['NVDA','AMD']))
    return service, TestClient(create_app(service)), run


@pytest.mark.parametrize('verdict',['supports','challenges','insufficient'])
def test_conclusion_verdict_idempotence_restart_export(tmp_path,verdict):
    service,client,run = setup(tmp_path)
    body = dict(version=2, decision_id='choice-1',verdict=verdict,note='My interpretation',
                evidence_ids=[] if verdict=='insufficient' else [run['citations'][0]['citation_id']])
    url = '/api/runs/'+run['run_id']+'/conclusion'
    response = client.post(url,json=body)
    assert response.status_code == 200, response.text
    assert client.post(url,json=body).json() == response.json()
    assert client.post(url,json={**body,'note':'conflict'}).status_code == 409
    revision = client.post(url,json={**body,'decision_id':'choice-2','note':'Reconsidered'})
    assert revision.status_code == 200
    assert revision.json()['supersedes'] == 'choice-1'
    service.close()
    service = ResearchWorkbenchService([FIXTURE],tmp_path/'runs.db')
    saved = service.read(run['run_id'])
    assert saved['user_conclusion']['note'] == 'Reconsidered'
    assert saved['conclusion_history'][0]['note'] == 'My interpretation'
    assert json.loads(service.export(run['run_id'])['content'])['result']['user_conclusion'] == saved['user_conclusion']
    service.close()


def test_evidence_must_belong_to_run_and_note_required_without_evidence(tmp_path):
    service,client,run = setup(tmp_path)
    url = '/api/runs/'+run['run_id']+'/conclusion'
    body = dict(version=2,decision_id='x',verdict='supports',note='Review',evidence_ids=['foreign'])
    assert client.post(url,json=body).status_code == 422
    assert client.post(url,json={**body,'evidence_ids':[]}).status_code == 422
    assert client.post(url,json={**body,'evidence_ids':[],'verdict':'insufficient','note':''}).status_code == 422
    service.close()


def test_legacy_decision_and_snapshot_untouched(tmp_path):
    service,client,run = setup(tmp_path)
    legacy = dict(narrative_id='growth-support',note='Legacy choice')
    service.choose(run['run_id'],legacy)
    raw = service.repository.connection.execute('SELECT result_body,decision_body FROM runs').fetchone()
    assert client.post('/api/runs/'+run['run_id']+'/conclusion',json=dict(version=2,decision_id='new',
        verdict='insufficient',note='More evidence needed',evidence_ids=[])).status_code == 200
    assert service.repository.connection.execute('SELECT result_body,decision_body FROM runs').fetchone() == raw
    assert service.read(run['run_id'])['decision'] == legacy
    # Additive migration: original ledger/decision readers can still open the same tables.
    from narrative_research_desk.ledger import open_ledger
    connection = open_ledger(tmp_path/'runs.db')
    assert connection.execute('SELECT decision_body FROM runs').fetchone()[0] == raw[1]
    connection.close()
    service.close()


def test_v2_backup_restores_every_revision(tmp_path):
    service,client,run = setup(tmp_path)
    for id,note in [('a','First'),('b','Second')]:
        service.conclude(run['run_id'],dict(version=2,decision_id=id,verdict='insufficient',note=note,evidence_ids=[]))
    backup = tmp_path/'copy.db'
    service.backup_to(backup)
    restored = ResearchWorkbenchService([FIXTURE],backup)
    assert restored.read(run['run_id'])['conclusion_history'] == service.read(run['run_id'])['conclusion_history']
    assert restored.export(run['run_id'])['content'] == service.export(run['run_id'])['content']
    restored.close()
    service.close()
