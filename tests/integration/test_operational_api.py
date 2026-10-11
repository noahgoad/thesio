from fastapi.testclient import TestClient
from narrative_research_desk.api import create_app


def app_for(tmp_path):
    service = lambda payload: {'sources': {}, 'material_claims': [], 'fact_ids': []}
    service.sources = {'fixture': {}}
    return create_app(service)


def client_for(tmp_path):
    return TestClient(app_for(tmp_path), base_url='http://127.0.0.1')


def test_readyz_exposes_read_only_state_and_no_fresh_quote_claim(tmp_path):
    with client_for(tmp_path) as client:
        response = client.get('/readyz')
        assert response.status_code == 200
        state = response.json()
        assert state['execution'] == 'NO_LIVE'
        assert state['paused'] is False
        assert state['fresh_market_data'] is False
        assert state['error_count'] == 0
        assert state['request_p95_ms'] is None
        assert response.headers['cache-control'] == 'no-store'


def test_pause_requires_local_origin_and_csrf_then_blocks_new_jobs(tmp_path):
    with client_for(tmp_path) as client:
        assert client.post('/api/pause', json={'paused': True}).status_code == 403
        assert client.get('/api/operator-token', headers={'Origin': 'https://evil.example'}).status_code == 403
        token = client.get('/api/operator-token').json()['csrf_token']
        headers = {'X-Operator-Token': token, 'Origin': 'http://127.0.0.1'}
        assert client.post('/api/pause', headers=headers, json={'paused': True}).status_code == 200
        state = client.get('/readyz').json()
        assert state['paused'] and not state['new_actions_allowed']
        assert 'OPERATOR_PAUSED' in state['degraded_reasons']
        for path in ['/api/analyze', '/api/runs', '/api/companies/prepare',
                     '/api/instruments/prepare', '/api/runs/r/explanation']:
            blocked = client.post(path, json={})
            assert blocked.status_code == 503
            assert blocked.json()['detail'] == 'OPERATOR_PAUSED'
        assert client.get('/healthz').json()['status'] == 'ok'
        assert client.get('/').status_code == 200
        assert client.post('/api/pause', headers=headers, json={'paused': False}).status_code == 200
        assert client.post('/api/analyze', json={}).status_code != 503


def test_operator_token_rejects_non_loopback_host_and_pause_coercion(tmp_path):
    with TestClient(app_for(tmp_path), base_url='http://public.example') as client:
        assert client.get('/api/operator-token').status_code == 403
    with client_for(tmp_path) as client:
        token = client.get('/api/operator-token').json()['csrf_token']
        assert client.post('/api/pause', headers={'X-Operator-Token': token},
                           json={'paused': 'true'}).status_code == 422


def test_failed_request_is_recorded_without_reset_on_resume(tmp_path):
    with client_for(tmp_path) as client:
        client.post('/api/analyze', json={})
        before = client.get('/readyz').json()
        assert before['error_count'] == 1
        assert before['active_requests'] == 0
        assert before['request_p95_ms'] is not None
        token = client.get('/api/operator-token').json()['csrf_token']
        client.post('/api/pause', headers={'X-Operator-Token': token}, json={'paused': False})
        after = client.get('/readyz').json()
        assert after['error_count'] == 1
        assert 'REQUEST_FAILURES_RECORDED' in after['degraded_reasons']


def test_readiness_uses_service_unavailable_status_when_paused(tmp_path):
    with client_for(tmp_path) as client:
        token = client.get('/api/operator-token').json()['csrf_token']
        client.post('/api/pause', headers={'X-Operator-Token': token}, json={'paused': True})
        assert client.get('/readyz').status_code == 503
