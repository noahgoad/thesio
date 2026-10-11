"""Bounded SEC acquisition and immutable, content-addressed local captures."""
from base64 import b64decode, b64encode
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from threading import RLock
import time
from urllib.request import Request, HTTPRedirectHandler, build_opener
from urllib.error import HTTPError, URLError

from narrative_research_desk.causal import utc_time
from narrative_research_desk.primary_sources import RetainedSEC

CATALOG_URL = 'https://www.sec.gov/files/company_tickers.json'
PREFIX = 'sec-selection-'
MAX_BYTES = 25_000_000


class SECProviderError(Exception):
    status_code = 503


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def fetch_sec(url, *, user_agent, timeout):
    """Only callers' fixed SEC URLs; reject redirects and oversized responses."""
    request = Request(url, headers={'User-Agent': user_agent, 'Accept': 'application/json'})
    with build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
        payload = response.read(MAX_BYTES + 1)
    if len(payload) > MAX_BYTES:
        raise ValueError('SEC_RESPONSE_TOO_LARGE')
    return payload


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


class SECCompanyDirectory:
    def __init__(self, cache_dir='.runtime/sec-cache', *, user_agent=None, fetch=None,
                 timeout=10, min_interval=0.2, catalog_ttl=86400, facts_ttl=21600,
                 now=None, monotonic=None, sleep=None):
        self.cache_dir = Path(cache_dir).resolve()
        self.user_agent = user_agent
        self.fetch = fetch or fetch_sec
        self.timeout = min(15, max(0.1, timeout))
        self.min_interval = max(0.2 if fetch is None else 0, min_interval)
        self.catalog_ttl, self.facts_ttl = catalog_ttl, facts_ttl
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.monotonic, self.sleep = monotonic or time.monotonic, sleep or time.sleep
        self._lock = RLock()
        self._last_request = None

    def _path(self, *parts):
        path = self.cache_dir.joinpath(*parts).resolve()
        if not path.is_relative_to(self.cache_dir):
            raise ValueError('SOURCE_PATH_INVALID')
        return path

    def _atomic(self, path, payload):
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.sec-', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as output:
                output.write(payload)
            os.replace(name, path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def _download(self, url):
        if (not isinstance(self.user_agent, str) or not self.user_agent.strip()
                or any(ord(c) < 32 or ord(c) > 126 for c in self.user_agent)):
            raise SECProviderError('SEC_USER_AGENT_REQUIRED: set C2_SEC_USER_AGENT to your declared application identity and real contact information.')
        if self._last_request is not None:
            delay = self.min_interval - (self.monotonic() - self._last_request)
            if delay > 0:
                self.sleep(delay)
        self._last_request = self.monotonic()
        try:
            payload = self.fetch(url, user_agent=self.user_agent, timeout=self.timeout)
            if not isinstance(payload, bytes) or len(payload) > MAX_BYTES:
                raise ValueError('SEC_RESPONSE_INVALID_OR_TOO_LARGE')
            json.loads(payload)
            return payload
        except Exception as error:
            reason = (f'SEC returned HTTP {error.code}' if isinstance(error, HTTPError) else
                      'request timed out' if isinstance(error, TimeoutError) else
                      'network connection failed' if isinstance(error, (URLError, OSError)) else
                      'SEC returned an invalid response')
            raise SECProviderError(f'SEC_FETCH_FAILED: {url}: {reason}. Check network access and the declared C2_SEC_USER_AGENT (SEC User-Agent); retry when SEC access is available. No substitute data was used.') from error

    def _cached(self, name, url, ttl):
        path = self._path(name)
        if path.exists():
            try:
                record = json.loads(path.read_bytes())
                seal = record.get('record_sha256')
                if seal != sha256(canonical({k: v for k, v in record.items() if k != 'record_sha256'})).hexdigest():
                    raise ValueError('record mismatch')
                payload = b64decode(record['payload'], validate=True)
                if (record['origin'] != url or sha256(payload).hexdigest() != record['sha256']
                        or len(payload) != record['byte_length']):
                    raise ValueError('mismatch')
                age = (self.now() - utc_time(record['captured_at'])).total_seconds()
                if age < 0:
                    raise ValueError('future capture')
                if age <= ttl:
                    return payload, record
            except (ValueError, KeyError, TypeError) as error:
                raise ValueError('SEC_CACHE_INTEGRITY') from error
        payload = self._download(url)
        record = {'origin': url, 'captured_at': self.now().isoformat(),
                  'sha256': sha256(payload).hexdigest(), 'byte_length': len(payload),
                  'payload': b64encode(payload).decode('ascii')}
        record['record_sha256'] = sha256(canonical(record)).hexdigest()
        self._atomic(path, canonical(record))
        return payload, record

    def _companies(self):
        payload, record = self._cached('catalog.json', CATALOG_URL, self.catalog_ttl)
        try:
            document = json.loads(payload)
            if not isinstance(document, dict) or not document:
                raise ValueError('empty catalog')
            companies = {}
            for row in document.values():
                ticker = row['ticker']
                cik = row['cik_str']
                if (not isinstance(ticker, str) or not re.fullmatch(r'[A-Z0-9._-]{1,32}', ticker)
                        or type(cik) is not int or not 0 < cik < 10**10
                        or not isinstance(row['title'], str) or not row['title'].strip()
                        or ticker in companies):
                    raise ValueError('invalid ticker mapping')
                companies[ticker] = {'ticker': ticker, 'name': row['title'], 'cik': f'{cik:010d}'}
        except (ValueError, KeyError, TypeError) as error:
            raise ValueError('SEC_CATALOG_INVALID') from error
        return companies, record

    def search(self, query=''):
        if not isinstance(query, str) or len(query) > 200:
            raise ValueError('COMPANY_QUERY_INVALID')
        with self._lock:
            companies, _ = self._companies()
            query = query.strip().casefold()
            matched = [c for c in companies.values() if query in c['ticker'].casefold()
                       or query in c['name'].casefold() or query in c['cik']]
            matched.sort(key=lambda c: (c['ticker'].casefold() != query,
                                       not c['ticker'].casefold().startswith(query), c['ticker']))
            return {'companies': matched[:50], 'total': len(companies), 'matched_total': len(matched)}

    def prepare(self, tickers):
        if (not isinstance(tickers, list) or not 1 <= len(tickers) <= 8
                or any(not isinstance(t, str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,32}', t) for t in tickers)):
            raise ValueError('COMPANY_SELECTION_INVALID: choose 1 to 8 SEC tickers')
        tickers = sorted(t.upper() for t in tickers)
        if len(set(tickers)) != len(tickers):
            raise ValueError('COMPANY_SELECTION_DUPLICATE')
        with self._lock:
            companies, mapping = self._companies()
            if any(t not in companies for t in tickers):
                raise ValueError('SEC_COMPANY_NOT_FOUND: search the official SEC directory before preparing')
            selected = [companies[t] for t in tickers]
            rows, bodies = [], {}
            for company in selected:
                ticker, cik = company['ticker'], company['cik']
                url = f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json'
                payload, record = self._cached(f'facts-{cik}.json', url, self.facts_ttl)
                document = json.loads(payload)
                if (not isinstance(document, dict) or type(document.get('cik')) is not int
                        or document['cik'] != int(cik) or not isinstance(document.get('facts'), dict)):
                    raise ValueError('SEC_COMPANYFACTS_IDENTITY_INVALID')
                bodies[ticker] = payload
                rows.append({'issuer_id': ticker, 'name': company['name'], 'relative_path': ticker + '.json',
                    'origin': url, 'captured_at': record['captured_at'], 'sha256': record['sha256'],
                    'byte_length': len(payload), 'permission': 'METADATA_ONLY', 'role': 'PRIMARY_EVIDENCE'})
            manifest = {'permission_scope': 'METADATA_ONLY', 'sources': rows, 'companies': selected,
                        'directory': {k: mapping[k] for k in ('origin', 'sha256', 'byte_length', 'captured_at')}}
            manifest_bytes = canonical(manifest)
            digest = sha256(manifest_bytes).hexdigest()
            target = self._path('captures', digest)
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                staging = Path(tempfile.mkdtemp(prefix='.capture-', dir=target.parent))
                try:
                    for ticker, payload in bodies.items():
                        (staging / (ticker + '.json')).write_bytes(payload)
                    (staging / 'directory.json').write_bytes(b64decode(mapping['payload']))
                    (staging / 'manifest.json').write_bytes(manifest_bytes)
                    try:
                        staging.rename(target)
                    except OSError:
                        if not target.is_dir():
                            raise
                finally:
                    if staging.exists():
                        shutil.rmtree(staging)
            reader = self.reader(PREFIX + digest)
            reader.verify(reader.read(tickers, max(row['captured_at'] for row in rows)))
            return {'source_id': reader.source_id, 'available_at': max(row['captured_at'] for row in rows),
                    'issuers': tickers, 'companies': selected}

    def reader(self, source_id):
        if not isinstance(source_id, str) or not re.fullmatch(PREFIX + r'[0-9a-f]{64}', source_id):
            raise ValueError('SEC_SOURCE_ID_INVALID')
        digest = source_id[len(PREFIX):]
        directory = self._path('captures', digest)
        manifest_path = directory / 'manifest.json'
        if manifest_path.resolve().parent != directory:
            raise ValueError('SOURCE_PATH_INVALID')
        try:
            payload = manifest_path.read_bytes()
        except FileNotFoundError as error:
            raise ValueError('LOCAL_SOURCE_UNAVAILABLE') from error
        if sha256(payload).hexdigest() != digest:
            raise ValueError('SOURCE_MANIFEST_MISMATCH')
        manifest = json.loads(payload)
        companies = manifest['companies']
        if not 1 <= len(companies) <= 8:
            raise ValueError('SOURCE_MANIFEST_INVALID')
        mapping = {c['ticker']: {'cik': c['cik'], 'legal_name': c['name']} for c in companies}
        reader = RetainedSEC(directory, issuers=mapping, source_id=source_id,
                             manifest_sha256=digest)
        reader._manifest()
        return reader
