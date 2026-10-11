"""Injected official-format SEC responses; no live network or factual-gold claims."""
import json
from copy import deepcopy
from datetime import datetime, timezone, timedelta

import pytest
from fastapi.testclient import TestClient

from narrative_research_desk.api import create_app
from narrative_research_desk.service import ResearchWorkbenchService
from narrative_research_desk import primary_sources
from narrative_research_desk.issuer_gate import CANONICAL_AI_SEMICONDUCTOR_UNIVERSE


CATALOG = {'0': {'ticker': 'AAPL', 'title': 'Apple Inc.', 'cik_str': 320193},
           '1': {'ticker': 'NVDA', 'title': 'NVIDIA Corporation', 'cik_str': 1045810}}


def facts(cik):
    return {'cik': cik, 'entityName': 'Injected issuer', 'facts': {'us-gaap': {
        'NetIncomeLoss': {'units': {'USD': [{'val': 42, 'start': '2025-01-01',
        'end': '2025-12-31', 'filed': '2026-02-01', 'form': '10-K', 'accn': 'fixture-a'}]}}}}}


def provider(tmp_path, **kwargs):
    from narrative_research_desk.sec_directory import SECCompanyDirectory
    calls = []
    def fetch(url, *, user_agent, timeout):
        calls.append((url, user_agent, timeout))
        assert 0 < timeout <= 15
        return json.dumps(CATALOG if url.endswith('company_tickers.json') else
                          facts(int(url.rsplit('CIK', 1)[1].split('.')[0]))).encode()
    return SECCompanyDirectory(tmp_path / 'sec-cache', user_agent='NarrativeResearchDesk/1.0',
                               fetch=fetch, min_interval=kwargs.pop('min_interval', 0), **kwargs), calls


def test_directory_search_prepare_cache_and_strict_original(tmp_path):
    directory, calls = provider(tmp_path)
    before = deepcopy(CANONICAL_AI_SEMICONDUCTOR_UNIVERSE)
    assert directory.search('apple') == {'companies': [{'ticker': 'AAPL', 'name': 'Apple Inc.',
                                                       'cik': '0000320193'}], 'total': 2, 'matched_total': 1}
    prepared = directory.prepare(['aapl'])
    assert prepared['issuers'] == ['AAPL']
    assert prepared['companies'][0]['name'] == 'Apple Inc.'
    assert directory.prepare(['AAPL']) == prepared
    assert len(calls) == 2
    reader = directory.reader(prepared['source_id'])
    assert reader.catalog()['source_id'] == prepared['source_id']
    result = reader.read(['AAPL'], prepared['available_at'])
    assert result['source_refs'][0]['name'] == 'Apple Inc.'
    assert result['facts'][0]['value'] == '42'
    reader.verify(result)
    assert primary_sources.RetainedSEC(reader.directory).catalog() is None
    assert CANONICAL_AI_SEMICONDUCTOR_UNIVERSE == before
    restarted, new_calls = provider(tmp_path)
    assert restarted.prepare(['AAPL']) == prepared and not new_calls


def test_unknown_company_analysis_export_restart_and_portfolio_gate(tmp_path):
    directory, _ = provider(tmp_path)
    ledger = tmp_path / 'runs.sqlite3'
    service = ResearchWorkbenchService([], ledger, company_directory=directory)
    client = TestClient(create_app(service))
    assert client.get('/api/capabilities').json()['company_directory']
    assert client.get('/api/companies?q=apple').json()['matched_total'] == 1
    response = client.post('/api/companies/prepare', json={'tickers': ['AAPL']})
    assert response.status_code == 200, response.text
    prepared = response.json()
    response = client.post('/api/analyze', json={'source_id': prepared['source_id'],
        'mode': 'PUBLIC_READ', 'watchlist': ['AAPL'], 'cutoff': prepared['available_at'],
        'question': 'Review net income', 'metric': 'net_income', 'operation': 'level', 'period_request': 'annual'})
    assert response.status_code == 200, response.text
    run = response.json()
    assert run['companies'] == prepared['companies'] and run['facts']
    assert 'Apple Inc.' in run['brief']['claims'][0]['text']
    body = {'positions': [{'issuer_id': 'AAPL', 'weight': '0.1'}], 'baskets': [
        {'narrative_id': card['narrative_id'], 'weights': {}} for card in run['narratives']]}
    assert 'POSITION_MAPPING' in client.post(f"/api/runs/{run['run_id']}/portfolio", json=body).text
    service.close()
    directory, calls = provider(tmp_path)
    service = ResearchWorkbenchService([], ledger, company_directory=directory)
    client = TestClient(create_app(service))
    for fmt in ('json', 'md'):
        response = client.get(f"/api/runs/{run['run_id']}/export?format={fmt}")
        assert response.status_code == 200, response.text
    assert client.get(f"/api/runs/{run['run_id']}").json()['source_id'] == prepared['source_id']
    assert not calls
    reader = directory.reader(prepared['source_id'])
    (reader.directory / 'AAPL.json').write_bytes(b'{}')
    response = client.get(f"/api/runs/{run['run_id']}/export")
    assert response.status_code == 422 and 'SOURCE_HASH_MISMATCH' in response.text
    service.close()


@pytest.mark.parametrize('tickers', [[], ['AAPL'] * 2, ['NOPE'], ['../AAPL'], ['AAPL'] * 9, 'AAPL'])
def test_invalid_selection(tmp_path, tickers):
    directory, _ = provider(tmp_path)
    with pytest.raises(ValueError):
        directory.prepare(tickers)


def test_network_failure_is_actionable_and_has_no_fallback(tmp_path):
    from narrative_research_desk.sec_directory import SECCompanyDirectory
    def fail(*args, **kwargs):
        raise TimeoutError('offline')
    directory = SECCompanyDirectory(tmp_path / 'sec-cache', fetch=fail,
                                    user_agent='NarrativeResearchDesk/1.0')
    client = TestClient(create_app(ResearchWorkbenchService([], company_directory=directory)))
    response = client.get('/api/companies?q=apple')
    assert response.status_code == 503
    assert response.json()['companies'] == [] and response.json()['total'] == 0
    assert 'SEC_FETCH_FAILED' in response.json()['error']
    assert 'User-Agent' in response.json()['error']
    assert client.post('/api/companies/prepare', json={'tickers': ['AAPL']}).status_code == 503


def test_capture_identity_rejects_manifest_tamper(tmp_path):
    directory, _ = provider(tmp_path)
    prepared = directory.prepare(['AAPL'])
    reader = directory.reader(prepared['source_id'])
    path = reader.directory / 'manifest.json'
    manifest = json.loads(path.read_bytes())
    manifest['companies'][0]['name'] = 'Changed'
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='SOURCE_MANIFEST_MISMATCH'):
        directory.reader(prepared['source_id'])


def test_cached_catalog_integrity(tmp_path):
    directory, calls = provider(tmp_path)
    directory.search('apple')
    path = directory.cache_dir / 'catalog.json'
    record = json.loads(path.read_bytes())
    record['sha256'] = '0' * 64
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match='SEC_CACHE_INTEGRITY'):
        directory.search('apple')
    assert len(calls) == 1


def test_default_service_does_not_enable_network():
    client = TestClient(create_app(ResearchWorkbenchService([])))
    assert not client.get('/api/capabilities').json().get('company_directory')
    assert client.get('/api/companies?q=apple').status_code == 503


def test_expired_facts_create_new_capture_preserving_old_bytes(tmp_path):
    instant = [datetime(2026, 10, 11, tzinfo=timezone.utc)]
    directory, calls = provider(tmp_path, now=lambda: instant[0], facts_ttl=60)
    old = directory.prepare(['AAPL'])
    old_reader = directory.reader(old['source_id'])
    old_manifest = (old_reader.directory / 'manifest.json').read_bytes()
    old_result = old_reader.read(['AAPL'], old['available_at'])
    instant[0] += timedelta(seconds=61)
    new = directory.prepare(['AAPL'])
    assert new['source_id'] != old['source_id'] and len(calls) == 3
    assert (old_reader.directory / 'manifest.json').read_bytes() == old_manifest
    old_reader.verify(old_result)


def test_capture_directory_integrity(tmp_path):
    directory, _ = provider(tmp_path)
    prepared = directory.prepare(['AAPL'])
    reader = directory.reader(prepared['source_id'])
    (reader.directory / 'directory.json').write_bytes(b'{}')
    with pytest.raises(ValueError, match='SEC_DIRECTORY_INTEGRITY'):
        directory.reader(prepared['source_id'])


def test_rate_limit_and_missing_useragent(tmp_path):
    clock = [0.0]
    sleeps = []
    def sleep(delay):
        sleeps.append(delay)
        clock[0] += delay
    directory, calls = provider(tmp_path, min_interval=.2, monotonic=lambda: clock[0], sleep=sleep)
    directory.prepare(['AAPL', 'NVDA'])
    assert sleeps == [.2, .2] and len(calls) == 3
    directory.user_agent = None
    with pytest.raises(Exception, match='SEC_USER_AGENT_REQUIRED'):
        directory._download('https://www.sec.gov/files/company_tickers.json')


def test_source_id_is_order_independent_and_selection_specific(tmp_path):
    directory, _ = provider(tmp_path)
    pair = directory.prepare(['NVDA', 'AAPL'])
    assert directory.prepare(['AAPL', 'NVDA']) == pair
    single = directory.prepare(['AAPL'])
    assert single['source_id'] != pair['source_id']
    with pytest.raises(ValueError, match='ISSUER_SOURCE_NOT_FOUND'):
        directory.reader(single['source_id']).read(['NVDA'], single['available_at'])
    with pytest.raises(ValueError, match='SOURCE_AFTER_CUTOFF'):
        directory.reader(single['source_id']).read(['AAPL'], '2020-01-01T00:00:00Z')


def test_cik_mismatch_and_prepare_body_bounds(tmp_path):
    directory, _ = provider(tmp_path)
    directory.fetch = lambda *args, **kwargs: json.dumps(facts(1)).encode()
    # Seed only the exact catalog bytes; the acquisition still validates CIK.
    good, _ = provider(tmp_path)
    good.search('apple')
    with pytest.raises(ValueError, match='SEC_COMPANYFACTS_IDENTITY_INVALID'):
        directory.prepare(['AAPL'])
    client = TestClient(create_app(ResearchWorkbenchService([], company_directory=good)))
    assert client.post('/api/companies/prepare', json={'tickers': ['AAPL'] * 9}).status_code == 422
    assert client.post('/api/companies/prepare', json={'tickers': ['AAPL'], 'url': 'https://example.com'}).status_code == 422
