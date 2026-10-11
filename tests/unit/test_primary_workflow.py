"""Synthetic structured API contracts; never gold or actual SEC observations."""
from hashlib import sha256
import json

import pytest
from narrative_research_desk.primary_sources import RetainedSEC
from narrative_research_desk.portfolio import compare_portfolio


def capture(tmp_path):
    document = {'cik': 1045810, 'facts': {'us-gaap': {'NetIncomeLoss': {'units': {'USD': [
        {'val': -10, 'start': '2026-01-01', 'end': '2026-03-31', 'filed': '2026-05-01', 'accn': 'synthetic-a', 'form': '10-Q'},
        {'val': -12, 'start': '2026-01-01', 'end': '2026-03-31', 'filed': '2026-05-02', 'accn': 'synthetic-b', 'form': '10-Q'},
        {'val': 999, 'start': '2026-04-01', 'end': '2026-06-30', 'filed': '2026-12-01', 'accn': 'synthetic-future', 'form': '10-Q'},
    ]}}}}}
    payload = json.dumps(document).encode()
    (tmp_path / 'NVDA.json').write_bytes(payload)
    manifest = {'permission_scope': 'METADATA_ONLY', 'sources': [{'issuer_id': 'NVDA', 'relative_path': 'NVDA.json',
        'origin': 'https://data.sec.gov/api/xbrl/companyfacts/CIK0001045810.json',
        'permission': 'METADATA_ONLY', 'role': 'PRIMARY_EVIDENCE', 'captured_at': '2026-09-24T00:00:00Z',
        'sha256': sha256(payload).hexdigest(), 'byte_length': len(payload)}]}
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    return RetainedSEC(tmp_path)


def test_retains_revisions_exact_values_and_omits_future(tmp_path):
    reader = capture(tmp_path)
    result = reader.read(['NVDA'], '2026-10-11T00:00:00Z')
    result['facts'][0]['basis'] = 'NON_GAAP'
    with pytest.raises(ValueError, match='STRUCTURED_FACT_MISMATCH'):
        reader.verify(result)
    result['facts'][0]['basis'] = 'GAAP'
    assert [f['value'] for f in result['facts']] == ['-10', '-12']
    assert len({f['fact_id'] for f in result['facts']}) == 2
    assert all(f['value'] is None for f in result['missing_facts'])
    reader.verify(result)
    result['facts'][0]['value'] = '11'
    with pytest.raises(ValueError, match='STRUCTURED_FACT_MISMATCH'):
        reader.verify(result)


def test_invalid_manifest_reports_unavailable(tmp_path):
    reader = capture(tmp_path)
    (tmp_path / 'manifest.json').write_text('[]')
    assert reader.catalog() is None
    (tmp_path / 'manifest.json').write_text('{')
    assert reader.catalog() is None
    reader = capture(tmp_path)
    manifest = json.loads((tmp_path / 'manifest.json').read_text())
    manifest['sources'][0]['captured_at'] = None
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    assert reader.catalog() is None


def test_path_containment_at_export_after_replacement(tmp_path):
    directory = tmp_path / 'captures'
    directory.mkdir()
    reader = capture(directory)
    result = reader.read(['NVDA'], '2026-10-11T00:00:00Z')
    external = tmp_path / 'external.json'
    original = directory / 'NVDA.json'
    external.write_bytes(original.read_bytes())
    original.unlink()
    try:
        original.symlink_to(external)
    except OSError:
        pytest.skip('Host does not permit file symlinks')
    assert reader.catalog() is None
    with pytest.raises(ValueError, match='SOURCE_PATH_INVALID'):
        reader.verify(result)


def test_gross_and_nonboolean_at_domain_boundary():
    run = {'watchlist': ['NVDA', 'AMD', 'AVGO'], 'mode': 'PUBLIC_READ',
           'narratives': [{'narrative_id':'a'}, {'narrative_id':'b'}],
           'facts': [{'issuer_id':issuer, 'fact_id':issuer+'-synthetic'} for issuer in ['NVDA','AMD','AVGO']]}
    body = {'positions': [], 'baskets': [{'narrative_id':'a','weights':{'NVDA':'.25','AMD':'.25','AVGO':'.15'}}, {'narrative_id':'b','weights':{}}]}
    with pytest.raises(ValueError, match='BASKET_GROSS_CAP'):
        compare_portfolio(run, body)
    body['baskets'][0]['weights'] = {'NVDA': True}
    with pytest.raises(ValueError, match='WEIGHT_INVALID'):
        compare_portfolio(run, body)
