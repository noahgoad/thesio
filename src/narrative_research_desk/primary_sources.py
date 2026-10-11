"""Read retained SEC API bytes locally; no network, filing-text or PIT claims."""
from datetime import date
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from narrative_research_desk.causal import utc_time
from narrative_research_desk.fact_units import extract_sec_companyfacts_facts
from narrative_research_desk.issuer_gate import CANONICAL_AI_SEMICONDUCTOR_UNIVERSE as CANONICAL_ISSUERS

SOURCE_ID = 'retained-sec-2026-09-24'
CONCEPTS = (
    'RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues',
    'RevenueFromContractWithCustomerIncludingAssessedTax', 'NetIncomeLoss',
    'PaymentsToAcquirePropertyPlantAndEquipment',
)


class RetainedSEC:
    def __init__(self, directory: str | Path, *, issuers=None, source_id=SOURCE_ID, manifest_sha256=None):
        self.directory = Path(directory).resolve()
        self.issuers = deepcopy(CANONICAL_ISSUERS if issuers is None else issuers)
        self.source_id = source_id
        self.manifest_sha256 = manifest_sha256

    def _path(self, name):
        path = (self.directory / name).resolve()
        if path.parent != self.directory or path.name != name:
            raise ValueError('SOURCE_PATH_INVALID')
        return path

    def _manifest(self):
        payload = self._path('manifest.json').read_bytes()
        if self.manifest_sha256 is not None and sha256(payload).hexdigest() != self.manifest_sha256:
            raise ValueError('SOURCE_MANIFEST_MISMATCH')
        manifest = json.loads(payload)
        if (not isinstance(manifest, dict) or manifest.get('permission_scope') != 'METADATA_ONLY'
                or not isinstance(manifest.get('sources'), list) or not manifest['sources']):
            raise ValueError('SOURCE_MANIFEST_INVALID')
        seen = set()
        for row in manifest['sources']:
            if not isinstance(row, dict):
                raise ValueError('SOURCE_MANIFEST_INVALID')
            issuer = row.get('issuer_id')
            if issuer not in self.issuers or issuer in seen:
                raise ValueError('SOURCE_MANIFEST_INVALID')
            seen.add(issuer)
            if (row.get('relative_path') != issuer + '.json' or row.get('permission') != 'METADATA_ONLY'
                    or row.get('role') != 'PRIMARY_EVIDENCE'
                    or not isinstance(row.get('sha256'), str) or len(row['sha256']) != 64
                    or any(c not in '0123456789abcdef' for c in row['sha256'])
                    or type(row.get('byte_length')) is not int or row['byte_length'] <= 0
                    or not isinstance(row.get('captured_at'), str)):
                raise ValueError('SOURCE_MANIFEST_INVALID')
            utc_time(row['captured_at'])
            if row.get('origin') != f"https://data.sec.gov/api/xbrl/companyfacts/CIK{self.issuers[issuer]['cik']}.json":
                raise ValueError('SOURCE_MANIFEST_INVALID')
            self._path(row['relative_path'])
        if self.manifest_sha256 is not None:
            metadata = manifest.get('directory', {})
            directory_bytes = self._path('directory.json').read_bytes()
            if (metadata.get('origin') != 'https://www.sec.gov/files/company_tickers.json'
                    or sha256(directory_bytes).hexdigest() != metadata.get('sha256')
                    or len(directory_bytes) != metadata.get('byte_length')):
                raise ValueError('SEC_DIRECTORY_INTEGRITY')
            catalog = json.loads(directory_bytes)
            companies = manifest.get('companies', [])
            if (not isinstance(catalog, dict) or len(companies) != len(self.issuers)
                    or set(self.issuers) != seen or {c['ticker'] for c in companies} != seen):
                raise ValueError('SOURCE_MANIFEST_INVALID')
            for company in companies:
                if not any(row.get('ticker') == company['ticker'] and row.get('title') == company['name']
                           and type(row.get('cik_str')) is int and f"{row['cik_str']:010d}" == company['cik']
                           for row in catalog.values() if isinstance(row, dict)):
                    raise ValueError('SEC_DIRECTORY_MAPPING_MISMATCH')
                source = next(row for row in manifest['sources'] if row['issuer_id'] == company['ticker'])
                if source.get('name') != company['name']:
                    raise ValueError('SEC_DIRECTORY_MAPPING_MISMATCH')
        return payload, manifest

    def catalog(self):
        try:
            _, manifest = self._manifest()
            if any(not self._path(row['relative_path']).is_file() for row in manifest['sources']):
                return None
        except (OSError, ValueError, KeyError, TypeError):
            return None
        return {'source_id': self.source_id, 'mode': 'PUBLIC_READ', 'local_only': True,
                'issuers': [row['issuer_id'] for row in manifest['sources']],
                'available_at': max(row['captured_at'] for row in manifest['sources']),
                'permission': manifest['permission_scope'], 'web_search': False}

    def read(self, issuers, cutoff, *, include_history=False):
        manifest_bytes, manifest = self._manifest()
        rows = {row['issuer_id']: row for row in manifest['sources']}
        facts, refs, missing, history = [], [], [], []
        for issuer in issuers:
            if issuer not in rows or issuer not in self.issuers:
                raise ValueError('ISSUER_SOURCE_NOT_FOUND')
            row = rows[issuer]
            path = self._path(row['relative_path'])
            payload = path.read_bytes()
            if sha256(payload).hexdigest() != row['sha256'] or len(payload) != row['byte_length']:
                raise ValueError('SOURCE_HASH_MISMATCH')
            cik = self.issuers[issuer]['cik']
            origin = f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json'
            if row['origin'] != origin or row['permission'] != 'METADATA_ONLY':
                raise ValueError('SOURCE_PROVENANCE_INVALID')
            available = utc_time(row['captured_at'])
            if available > utc_time(cutoff):
                raise ValueError('SOURCE_AFTER_CUTOFF')
            document = json.loads(payload)
            source_id = f'sec-companyfacts:{issuer}:{row["sha256"]}'
            refs.append({**row, 'name': self.issuers[issuer]['legal_name'], 'source_id': source_id, 'available_at': row['captured_at'],
                         'availability_basis': 'LOCAL_CAPTURE_ONLY', 'published_at': None,
                         'source_version': 'retained-json-v1'})
            for concept in CONCEPTS:
                parsed = extract_sec_companyfacts_facts(payload, issuer_id=issuer, expected_cik=cik,
                    source_id=source_id, taxonomy='us-gaap', concept=concept)
                # Only use duration USD observations with explicit accession/form/date metadata.
                candidates = []
                for fact in parsed:
                    if fact['unit'] != 'USD' or fact['form'] not in {'10-K', '10-Q', '10-K/A', '10-Q/A'} or not fact['accession']:
                        continue
                    try:
                        start, end, filed = (date.fromisoformat(fact[key]) for key in ('start', 'end', 'filed'))
                    except (ValueError, TypeError):
                        continue
                    if start > end or end > filed or filed > available.date():
                        continue
                    candidates.append(fact)
                if not candidates:
                    missing.append({'issuer_id': issuer, 'metric': concept, 'value': None, 'reason': 'NO_ELIGIBLE_RETAINED_USD_DURATION_FACT'})
                    continue
                latest_end = max(f['end'] for f in candidates)
                history_ends = set()
                if include_history:
                    from narrative_research_desk.period_comparison import period_type
                    for kind in ('annual', 'quarterly'):
                        ends = sorted({f['end'] for f in candidates if period_type(f) == kind}, reverse=True)
                        if ends:
                            history_ends.add(ends[0])
                            # Only the latest and its actual prior-year counterpart, never adjacent quarters.
                            current_end = date.fromisoformat(ends[0])
                            history_ends.update(end for end in ends[1:] if 350 <= (current_end-date.fromisoformat(end)).days <= 380)
                candidates = [f for f in candidates if f['end'] == latest_end or f['end'] in history_ends]
                # Preserve every start/accession/value at latest end; never average revisions or YTD/quarter.
                observations = document['facts']['us-gaap'][concept]['units']['USD']
                seen = set()
                for fact in candidates:
                    for index, observation in enumerate(observations):
                        if (str(observation.get('val')) == str(fact['value']) and
                            all(observation.get(key) == fact[key] for key in ('start', 'end', 'filed')) and
                            observation.get('accn') == fact['accession']):
                            pointer = f'/facts/us-gaap/{concept}/units/USD/{index}'
                            identity = (fact['start'], fact['end'], fact['accession'], str(fact['value']))
                            if identity not in seen:
                                seen.add(identity)
                                retained_fact = {**fact, 'fact_id': sha256((source_id + pointer).encode()).hexdigest(),
                                    'value': str(fact['value']), 'currency': 'USD', 'json_pointer': pointer,
                                    'original_observation': observation, 'origin': origin,
                                    'available_at': row['captured_at'], 'published_at': None,
                                    'availability_basis': 'LOCAL_CAPTURE_ONLY', 'permission': 'METADATA_ONLY',
                                    'verification': 'HASH_AND_STRUCTURED_POINTER', 'independent_review': 'NOT_REVIEWED'}
                                if fact['end'] == latest_end:
                                    facts.append(retained_fact)
                                if include_history and fact['end'] in history_ends:
                                    history.append({**retained_fact, 'revision': fact['accession']})
                            break
        result = {'facts': facts, 'source_refs': refs, 'missing_facts': missing,
                  'manifest_sha256': sha256(manifest_bytes).hexdigest()}
        if include_history:
            for fact in history:
                fact['supersedes_fact_ids'] = [previous['fact_id'] for previous in history
                    if all(fact[key] == previous[key] for key in ('issuer_id','metric','start','end','unit'))
                    and previous['filed'] < fact['filed']]
            result['fact_history'] = history
        return result

    def verify(self, result):
        manifest_bytes, manifest = self._manifest()
        if sha256(manifest_bytes).hexdigest() != result['manifest_sha256']:
            raise ValueError('SOURCE_MANIFEST_MISMATCH')
        rows = {row['issuer_id']: row for row in manifest['sources']}
        sources = {source['source_id']: source for source in result['source_refs']}
        all_facts = result['facts'] + result.get('fact_history', [])
        if any(fact['source_id'] not in sources for fact in all_facts):
            raise ValueError('STRUCTURED_FACT_MISMATCH')
        for source in result['source_refs']:
            if source['issuer_id'] not in self.issuers:
                raise ValueError('SOURCE_PROVENANCE_INVALID')
            if any(source.get(key) != value for key, value in rows[source['issuer_id']].items()):
                raise ValueError('SOURCE_PROVENANCE_INVALID')
            payload = self._path(source['issuer_id'] + '.json').read_bytes()
            if sha256(payload).hexdigest() != source['sha256']:
                raise ValueError('SOURCE_HASH_MISMATCH')
            document = json.loads(payload)
            for fact in (f for f in all_facts if f['source_id'] == source['source_id']):
                node = document
                for token in fact['json_pointer'].split('/')[1:]:
                    node = node[int(token)] if isinstance(node, list) else node[token]
                expected_pointer = f"/facts/us-gaap/{fact['metric']}/units/{fact['unit']}/"
                if (not fact['json_pointer'].startswith(expected_pointer) or
                        node != fact['original_observation'] or str(node['val']) != fact['value'] or
                        fact['fact_id'] != sha256((fact['source_id'] + fact['json_pointer']).encode()).hexdigest() or
                        fact['source_sha256'] != source['sha256'] or fact['origin'] != source['origin'] or
                        fact['issuer_id'] != source['issuer_id'] or fact['basis'] != 'GAAP' or
                        fact.get('currency') != 'USD' or fact.get('taxonomy') != 'us-gaap' or
                        ('revision' in fact and fact['revision'] != node.get('accn')) or
                        fact['available_at'] != source['captured_at'] or fact['published_at'] is not None or
                        fact['accession'] != node.get('accn') or
                        any(fact[key] != node.get(key) for key in ('start', 'end', 'filed', 'form'))):
                    raise ValueError('STRUCTURED_FACT_MISMATCH')
        for fact in result.get('fact_history', []):
            expected = [previous['fact_id'] for previous in result['fact_history']
                if all(fact[key] == previous[key] for key in ('issuer_id','metric','start','end','unit'))
                and previous['filed'] < fact['filed']]
            if fact.get('supersedes_fact_ids') != expected:
                raise ValueError('STRUCTURED_FACT_MISMATCH')
        if 'brief' in result:
            known = {f['fact_id']:f for f in all_facts}
            for fact in result['brief']['evidence_rows']:
                if fact != known.get(fact['fact_id']):
                    raise ValueError('BRIEF_FACT_BINDING_MISMATCH')
            if any(not claim['fact_ids'] or not set(claim['fact_ids']) <= known.keys() for claim in result['brief']['claims']):
                raise ValueError('BRIEF_FACT_BINDING_MISMATCH')
