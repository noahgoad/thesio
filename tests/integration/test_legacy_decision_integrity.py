"""Legacy choices stay readable; new choices are sealed without legacy backfill."""
import json

import pytest

from tests.integration.test_research_conclusion import setup, FIXTURE
from narrative_research_desk.service import ResearchWorkbenchService


@pytest.mark.parametrize('decision',[{'narrative_id':'invented','note':'tampered'},
    {'narrative_id':'growth-support','note':'tampered','run_id':'foreign'},
    {'narrative_id':'growth-support','note':{'invalid':'object'}}, []])
def test_unsealed_legacy_decision_must_belong_to_parent_run(tmp_path,decision):
    service,client,run = setup(tmp_path)
    service.repository.connection.execute('UPDATE runs SET decision_body=? WHERE run_id=?',
        (json.dumps(decision),run['run_id']))
    for url in ('/api/runs/'+run['run_id'], '/api/runs/'+run['run_id']+'/export'):
        response = client.get(url)
        assert response.status_code == 422
        assert response.json()['detail'] == 'DECISION_INVALID'
    service.close()


def test_new_decision_tamper_to_another_valid_choice_or_note_fails(tmp_path):
    service,client,run = setup(tmp_path)
    service.choose(run['run_id'],{'narrative_id':'growth-support','note':'original'})
    for decision in ({'narrative_id':'margin-risk','note':'original'}, {'narrative_id':'growth-support','note':'edited'}):
        service.repository.connection.execute('UPDATE runs SET decision_body=? WHERE run_id=?',
            (json.dumps(decision),run['run_id']))
        response = client.get('/api/runs/'+run['run_id'])
        assert response.status_code == 422
        assert response.json()['detail'] == 'DECISION_INTEGRITY_MISMATCH'
        assert client.get('/api/runs/'+run['run_id']+'/export').status_code == 422
    service.close()


def test_valid_unsealed_legacy_retry_does_not_backfill_integrity(tmp_path):
    service,_,run = setup(tmp_path)
    legacy = {'narrative_id':'growth-support','note':'Legacy choice'}
    service.repository.connection.execute('UPDATE runs SET decision_body=? WHERE run_id=?',
        (json.dumps(legacy),run['run_id']))
    service.repository.connection.commit()
    service.close()
    service = ResearchWorkbenchService([FIXTURE], tmp_path/'runs.db')
    before = service.ledger_state_digest()
    assert service.read(run['run_id'])['decision'] == legacy
    assert service.choose(run['run_id'], legacy) == legacy
    assert json.loads(service.export(run['run_id'])['content'])['result']['decision'] == legacy
    assert service.repository.connection.execute('SELECT COUNT(*) FROM research_decision_integrity').fetchone()[0] == 0
    assert service.ledger_state_digest() == before
    service.close()


def test_new_seal_survives_restart_and_backup(tmp_path):
    service,_,run = setup(tmp_path)
    decision = {'narrative_id':'growth-support','note':'new'}
    assert service.choose(run['run_id'],decision) == decision
    assert service.choose(run['run_id'],decision) == decision
    assert service.repository.connection.execute('SELECT COUNT(*) FROM research_decision_integrity').fetchone()[0] == 1
    service.backup_to(tmp_path/'backup.db')
    service.close()
    for path in (tmp_path/'runs.db',tmp_path/'backup.db'):
        restored = ResearchWorkbenchService([FIXTURE],path)
        assert restored.read(run['run_id'])['decision'] == decision
        restored.repository.connection.execute('UPDATE runs SET decision_body=NULL WHERE run_id=?',(run['run_id'],))
        with pytest.raises(ValueError,match='DECISION_INTEGRITY_MISMATCH'):
            restored.read(run['run_id'])
        restored.close()
