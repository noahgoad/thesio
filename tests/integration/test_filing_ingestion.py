"""Local synthetic filing fixtures: no SEC fetch or human adjudication."""
import base64
from hashlib import sha256
import json
import socket

import pytest
from fastapi.testclient import TestClient

from narrative_research_desk.api import create_app
from narrative_research_desk.service import ResearchWorkbenchService

RAW = b'<html><head><script>alert(1)</script></head><body><p>Revenue grew &amp; demand rose.</p><p>Margins fell.</p></body></html>'
ORIGIN = 'https://www.sec.gov/Archives/edgar/data/1045810/000104581026000001/nvda-10k.htm'


def filing(raw=RAW, **changes):
    return dict(raw_base64=base64.b64encode(raw).decode(), format='html', issuer_id='NVDA',
                cik='1045810', accession='0001045810-26-000001', origin=ORIGIN,
                permission='LICENSED', published_at='2026-02-01T00:00:00Z', **changes)


def quotes():
    return [{'stance': 'support', 'quote': 'Revenue grew & demand rose.', 'issuer_id': 'NVDA'},
            {'stance': 'challenge', 'quote': 'Margins fell.', 'issuer_id': 'NVDA'}]


def test_preview_import_restart_review_export_no_network(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Network is forbidden')
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    path = tmp_path / 'filings.sqlite3'
    service = ResearchWorkbenchService([], path)
    client = TestClient(create_app(service))
    preview = client.post('/api/filings/preview', json=filing())
    assert preview.status_code == 200, preview.text[:300]
    doc = preview.json()
    assert doc['text'] == 'Revenue grew & demand rose.\nMargins fell.\n'
    assert doc['raw_sha256'] == sha256(RAW).hexdigest()
    assert doc['text_sha256'] == sha256(doc['text'].encode()).hexdigest()
    assert doc['cik'] == '0001045810'
    assert doc['published_at_basis'] == 'USER_ASSERTED'
    assert doc['origin_validation'] == 'SEC_ARCHIVE_PATH_CIK_MATCH_ONLY'
    assert doc['authenticity'] == 'NOT_VERIFIED'
    assert doc['historical_pit_proven'] is False
    response = client.post('/api/filings', json={**filing(), 'evidence': quotes()})
    assert response.status_code == 201, response.text
    source = response.json()
    retained = service.repository.get_source(source['source_id'])
    assert base64.b64decode(retained['raw_base64']) == RAW
    assert retained['publication_allowed'] is False
    assert 'raw_base64' not in source
    service.close()
    service = ResearchWorkbenchService([], path)
    client = TestClient(create_app(service))
    request = dict(source_id=source['source_id'], mode='USER_SUPPLIED', cutoff=source['available_at'],
                   question='Growth durable?', watchlist=['NVDA'], run_id='filing-run')
    result = client.post('/api/analyze', json=request)
    assert result.status_code == 200, result.text
    data = result.json()
    assert data['decision'] is None
    assert data['source_document']['independent_review'] == 'NOT_REVIEWED'
    for citation in data['citations']:
        assert citation['source_sha256'] == doc['text_sha256']
        assert citation['raw_sha256'] == doc['raw_sha256']
        assert citation['raw_ranges']
        assert doc['text'][citation['start']:citation['end']] == citation['quote']
    assert client.post('/api/analyze', json=request).json() == data
    exported = client.get('/api/runs/filing-run/export')
    assert exported.status_code == 200
    assert 'raw_base64' not in exported.json()['result']['source_document']
    assert doc['raw_sha256'] in exported.json()['source_hashes']
    assert exported.json()['result']['decision'] is None
    service.close()


@pytest.mark.parametrize('field,value', [
    ('origin', 'https://www.sec.gov.evil.test/Archives/edgar/data/1045810/000104581026000001/x.htm'),
    ('origin', ORIGIN.replace('1045810/', '2488/')),
    ('origin', 'file:///C:/secret.htm'), ('origin', 'javascript:alert(1)'),
    ('origin', ORIGIN + '?token=secret'), ('origin', ORIGIN.replace('https:', 'http:')),
    ('origin', ORIGIN.replace('www.sec.gov', 'user@www.sec.gov')),
    ('origin', ORIGIN.replace('nvda-10k.htm', '%2e%2e/x.htm')),
    ('cik', '2488'), ('issuer_id', 'UNKNOWN'), ('permission', 'METADATA_ONLY'),
    ('raw_base64', 'not base64'), ('format', 'pdf'), ('published_at', '2026-02-01'),
])
def test_reject_invalid_identity_origin_permission_encoding(field, value):
    service = ResearchWorkbenchService([])
    client = TestClient(create_app(service))
    payload = filing()
    payload[field] = value
    response = client.post('/api/filings', json=payload)
    assert response.status_code == 422, response.text
    assert service.repository.connection.execute('SELECT COUNT(*) FROM research_sources').fetchone()[0] == 0
    service.close()


@pytest.mark.parametrize('raw', [b'x' * (4 * 1024 * 1024 + 1), b'\xff', b'abc\x00def',
    b'<!DOCTYPE html [<!ENTITY leak SYSTEM "file:///secret">]><p>&leak;</p>',
    b'<div>' * 300 + b'x' + b'</div>' * 300], ids=['oversize', 'encoding', 'nul', 'entity', 'depth'])
def test_oversized_invalid_and_hostile_parser_inputs(raw):
    service = ResearchWorkbenchService([])
    response = TestClient(create_app(service)).post('/api/filings/preview', json=filing(raw))
    assert response.status_code in {413, 422}, response.text
    service.close()


def test_full_filing_size_separate_from_text_limit():
    service = ResearchWorkbenchService([])
    client = TestClient(create_app(service))
    # Synthetic 1,967,816-byte full HTML-sized input, not a captured NVIDIA filing.
    prefix, suffix = b'<html><!--', b'--><body><p>Revenue grew.</p></body></html>'
    raw = prefix + b'x' * (1_967_816 - len(prefix) - len(suffix)) + suffix
    preview = client.post('/api/filings/preview', json=filing(raw))
    assert preview.status_code == 200, preview.text[:300]
    assert preview.json()['raw_byte_length'] == 1_967_816
    assert preview.json()['text'] == 'Revenue grew.\n'
    assert client.post('/api/filings', json={**filing(raw), 'evidence': [quotes()[0] | {'quote': 'Revenue grew.'}]}).status_code == 201
    service.close()


def test_extracted_text_has_independent_size_bound():
    service = ResearchWorkbenchService([])
    response = TestClient(create_app(service)).post('/api/filings/preview', json=filing(b'<p>' + b'x' * (2 * 1024 * 1024 + 1) + b'</p>'))
    assert response.status_code == 422
    assert response.json()['detail'] == 'FILING_EXTRACTION_LIMIT', response.text[:300]
    service.close()


def test_active_hidden_content_and_external_resources_are_never_rendered():
    raw = b'<p>Visible</p><script src="https://evil.test/x">secret</script><style>secret</style><iframe src="file:///secret">secret</iframe><svg><text>secret</text></svg><div hidden>secret</div><div style="display:none">secret</div><ix:hidden>secret</ix:hidden><img src="https://evil.test/x" onerror="alert(1)"><p>Risk</p>'
    service = ResearchWorkbenchService([])
    doc = TestClient(create_app(service)).post('/api/filings/preview', json=filing(raw))
    assert doc.status_code == 200, doc.text
    assert doc.json()['text'] == 'Visible\nRisk\n'
    assert all(0 <= s['raw_start'] < s['raw_end'] <= len(raw) for s in doc.json()['segments'] if s['raw_start'] is not None)
    service.close()


def test_duplicate_quote_requires_offset_and_other_issuer_is_rejected():
    service = ResearchWorkbenchService([])
    client = TestClient(create_app(service))
    payload = filing(b'<p>Risk</p><p>Risk</p>')
    evidence = [{'stance': 'challenge', 'quote': 'Risk', 'issuer_id': 'NVDA'}]
    assert client.post('/api/filings', json={**payload, 'evidence': evidence}).status_code == 422
    evidence[0]['start'] = 5
    source = client.post('/api/filings', json={**payload, 'evidence': evidence})
    assert source.status_code == 201, source.text
    evidence[0]['issuer_id'] = 'AMD'
    assert client.post('/api/filings', json={**payload, 'evidence': evidence}).status_code == 422
    service.close()


@pytest.mark.parametrize('field', ['raw_base64', 'text', 'segments', 'raw_sha256', 'origin'])
def test_retained_tampering_rejected_on_replay_and_export(field):
    service = ResearchWorkbenchService([])
    client = TestClient(create_app(service))
    source = client.post('/api/filings', json={**filing(), 'evidence': quotes()})
    assert source.status_code == 201, source.text
    source = source.json()
    request = dict(source_id=source['source_id'], mode='USER_SUPPLIED', cutoff=source['available_at'],
                   question='Growth?', watchlist=['NVDA'], run_id='tamper-run')
    assert client.post('/api/analyze', json=request).status_code == 200
    row = service.repository.get_source(source['source_id'])
    row[field] = [] if field == 'segments' else 'tampered'
    with service.repository.connection:
        service.repository.connection.execute('UPDATE research_sources SET body=? WHERE source_id=?', (json.dumps(row), source['source_id']))
    assert client.post('/api/analyze', json=request).status_code == 422
    assert client.get('/api/runs/tamper-run/export').status_code == 422
    service.close()


@pytest.mark.parametrize('target', ['snapshot_kind', 'source_identity', 'saved_citation', 'missing_seal', 'identity_and_mode_without_seal'])
def test_saved_filing_run_cannot_downgrade_integrity_gate(target):
    service = ResearchWorkbenchService([])
    client = TestClient(create_app(service))
    source = client.post('/api/filings', json={**filing(), 'evidence': quotes()}).json()
    request = dict(source_id=source['source_id'], mode='USER_SUPPLIED', cutoff=source['available_at'],
                   question='Growth?', watchlist=['NVDA'], run_id='kind-tamper-run')
    assert client.post('/api/analyze', json=request).status_code == 200
    saved = service.repository.get('kind-tamper-run')
    if target == 'saved_citation':
        saved['citations'][0]['quote'] = 'fabricated'
    else:
        saved['source_document']['kind'] = 'USER_NOTES'
        saved['source_document']['raw_sha256'] = 'tampered'
        if target == 'source_identity':
            saved['source_id'] = 'supplied-fake'
        if target == 'missing_seal':
            saved.pop('filing_run_sha256', None)
        if target == 'identity_and_mode_without_seal':
            saved.pop('filing_run_sha256', None)
            saved['source_id'] = 'supplied-fake'
            saved['mode'] = 'USER_SUPPLIED'
            saved['source_document'].pop('record_sha256', None)
    with service.repository.connection:
        service.repository.connection.execute('UPDATE runs SET result_body=? WHERE run_id=?',
                                             (json.dumps(saved), 'kind-tamper-run'))
    for route in ['/api/runs/kind-tamper-run', '/api/runs/kind-tamper-run/export']:
        assert client.get(route).status_code == 422
    assert client.post('/api/analyze', json=request).status_code == 422
    assert client.post('/api/runs/kind-tamper-run/decision', json={'narrative_id': 'support'}).status_code == 422
    assert service.repository.connection.execute('SELECT decision_body FROM runs WHERE run_id=?', ('kind-tamper-run',)).fetchone()[0] is None
    service.close()


def test_decision_write_rejects_corrupt_retained_filing_and_leaves_decision_empty():
    service = ResearchWorkbenchService([])
    client = TestClient(create_app(service))
    source = client.post('/api/filings', json={**filing(), 'evidence': quotes()}).json()
    request = dict(source_id=source['source_id'], mode='USER_SUPPLIED', cutoff=source['available_at'],
                   question='Growth?', watchlist=['NVDA'], run_id='decision-tamper-run')
    assert client.post('/api/analyze', json=request).status_code == 200
    retained = service.repository.get_source(source['source_id'])
    retained['raw_base64'] = base64.b64encode(b'corrupt').decode()
    with service.repository.connection:
        service.repository.connection.execute('UPDATE research_sources SET body=? WHERE source_id=?',
                                             (json.dumps(retained), source['source_id']))
    assert client.get('/api/runs/decision-tamper-run').status_code == 422
    response = client.post('/api/runs/decision-tamper-run/decision', json={'narrative_id': 'support', 'note': 'Test only'})
    assert response.status_code == 422
    assert service.repository.get('decision-tamper-run')['decision'] is None
    service.close()


def test_valueless_aria_hidden_attribute_is_safe_visible_text():
    service = ResearchWorkbenchService([])
    client = TestClient(create_app(service))
    body = filing(b'<div aria-hidden>Revenue.</div>')
    response = client.post('/api/filings/preview', json=body)
    assert response.status_code == 200, response.text
    assert response.json()['text'] == 'Revenue.\n'
    body['evidence'] = [{'issuer_id': 'NVDA', 'stance': 'support', 'quote': 'Revenue.'}]
    assert client.post('/api/filings', json=body).status_code == 201
    service.close()


def test_valid_filing_decision_still_exports_and_replays(tmp_path):
    path = tmp_path / 'decision.sqlite3'
    service = ResearchWorkbenchService([], path)
    client = TestClient(create_app(service))
    source = client.post('/api/filings', json={**filing(), 'evidence': quotes()}).json()
    request = dict(source_id=source['source_id'], mode='USER_SUPPLIED', cutoff=source['available_at'],
                   question='Growth?', watchlist=['NVDA'], run_id='valid-decision-run')
    assert client.post('/api/analyze', json=request).status_code == 200
    decision = {'narrative_id': 'support', 'note': 'Automated fixture test only'}
    assert client.post('/api/runs/valid-decision-run/decision', json=decision).status_code == 200
    service.close()
    service = ResearchWorkbenchService([], path)
    client = TestClient(create_app(service))
    assert client.get('/api/runs/valid-decision-run').json()['decision'] == decision
    assert client.post('/api/analyze', json=request).json()['decision'] == decision
    exported = client.get('/api/runs/valid-decision-run/export')
    assert exported.status_code == 200
    assert exported.json()['result']['decision'] == decision
    service.close()


def test_saved_body_checksum_is_independent_of_mutable_snapshot_fields():
    service = ResearchWorkbenchService([])
    client = TestClient(create_app(service))
    source = client.post('/api/filings', json={**filing(), 'evidence': quotes()}).json()
    request = dict(source_id=source['source_id'], mode='USER_SUPPLIED', cutoff=source['available_at'],
                   question='Growth?', watchlist=['NVDA'], run_id='sqlite-seal-run')
    assert client.post('/api/analyze', json=request).status_code == 200
    saved = service.repository.get('sqlite-seal-run')
    saved.pop('filing_run_sha256', None)
    saved['source_document'] = {'kind': 'NOTES'}
    saved['source_id'] = 'supplied-fake'
    saved['mode'] = 'FIXTURE'
    with service.repository.connection:
        service.repository.connection.execute('UPDATE runs SET result_body=? WHERE run_id=?',
                                             (json.dumps(saved), 'sqlite-seal-run'))
    with pytest.raises(ValueError, match='RUN_RESULT_HASH_MISMATCH'):
        service.repository.get('sqlite-seal-run')
    assert client.get('/api/runs/sqlite-seal-run').status_code == 422
    assert client.get('/api/runs/sqlite-seal-run/export').status_code == 422
    assert client.post('/api/runs/sqlite-seal-run/decision', json={'narrative_id': 'support'}).status_code == 422
    service.close()


def test_legacy_filing_rows_are_not_silently_sealed_on_upgrade(tmp_path):
    path = tmp_path / 'legacy.sqlite3'
    service = ResearchWorkbenchService([], path)
    client = TestClient(create_app(service))
    source = client.post('/api/filings', json={**filing(), 'evidence': quotes()}).json()
    request = dict(source_id=source['source_id'], mode='USER_SUPPLIED', cutoff=source['available_at'],
                   question='Growth?', watchlist=['NVDA'], run_id='legacy-run')
    assert client.post('/api/analyze', json=request).status_code == 200
    with service.repository.connection:
        service.repository.connection.execute('DELETE FROM research_run_integrity WHERE run_id=?', ('legacy-run',))
    service.close()
    service = ResearchWorkbenchService([], path)
    client = TestClient(create_app(service))
    assert client.get('/api/runs/legacy-run').status_code == 422
    assert service.repository.connection.execute('SELECT COUNT(*) FROM research_run_integrity WHERE run_id=?', ('legacy-run',)).fetchone()[0] == 0
    service.close()


@pytest.mark.parametrize('change_body_id', [False, True])
def test_first_analysis_uses_lookup_identity_and_creates_no_run_on_tampering(change_body_id):
    service = ResearchWorkbenchService([])
    client = TestClient(create_app(service))
    source = client.post('/api/filings', json={**filing(), 'evidence': quotes()}).json()
    retained = service.repository.get_source(source['source_id'])
    retained['kind'] = 'NOTES'
    retained['raw_base64'] = base64.b64encode(b'corrupt raw').decode()
    if change_body_id:
        retained['source_id'] = 'supplied-fake'
        for evidence in retained['evidence']:
            evidence['source_id'] = 'supplied-fake'
    with service.repository.connection:
        service.repository.connection.execute('UPDATE research_sources SET body=? WHERE source_id=?',
                                             (json.dumps(retained), source['source_id']))
    request = dict(source_id=source['source_id'], mode='USER_SUPPLIED', cutoff=source['available_at'],
                   question='Growth?', watchlist=['NVDA'], run_id='first-tamper-run')
    assert client.post('/api/analyze', json=request).status_code == 422
    assert service.repository.connection.execute('SELECT COUNT(*) FROM runs').fetchone()[0] == 0
    assert service.repository.connection.execute('SELECT COUNT(*) FROM research_run_integrity').fetchone()[0] == 0
    service.close()


def test_full_size_many_quotes_decode_once_per_operation(monkeypatch, record_property):
    from time import perf_counter
    import narrative_research_desk.filings as parser
    count = 0
    original = parser.decode_raw
    def counted(encoded):
        nonlocal count
        count += 1
        return original(encoded)
    monkeypatch.setattr(parser, 'decode_raw', counted)
    html = b'<!--' + b'x' * 1_967_816 + b'-->'
    html += b''.join(f'<p>Quote {i:02d}.</p>'.encode() for i in range(30))
    evidence = [{'stance': 'support' if i % 2 else 'challenge', 'quote': f'Quote {i:02d}.', 'issuer_id': 'NVDA'} for i in range(30)]
    service = ResearchWorkbenchService([])
    start = perf_counter()
    source = service.ingest_filing({**filing(html), 'evidence': evidence})
    elapsed = perf_counter() - start
    record_property('full_size_import_seconds', elapsed)
    assert count == 1, 'Whole-file decoding must not scale with quote count'
    assert elapsed < 5, f'Bounded synthetic full-file import took {elapsed:.3f}s'
    retained = service.repository.get_source(source['source_id'])
    count = 0
    start = perf_counter()
    parser.verify_filing(retained)
    elapsed = perf_counter() - start
    record_property('full_size_verify_seconds', elapsed)
    assert count == 1
    assert elapsed < 5, f'Bounded synthetic full-file verification took {elapsed:.3f}s'
    count = 0
    result = service.analyze(dict(source_id=source['source_id'], mode='USER_SUPPLIED', cutoff=source['available_at'],
                                  question='Growth?', watchlist=['NVDA'], run_id='bounded-run'))
    assert count == 1
    count = 0
    service.read(result['run_id'])
    assert count == 1
    service.close()
