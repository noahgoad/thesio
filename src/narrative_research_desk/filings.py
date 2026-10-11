"""Bounded, offline filing ingestion. URL consistency is not document authenticity."""
import base64
from array import array
import binascii
from hashlib import sha256
from html import unescape
from html.parser import HTMLParser
import json
import re

from narrative_research_desk.causal import utc_time
from narrative_research_desk.issuer_gate import CANONICAL_AI_SEMICONDUCTOR_UNIVERSE

MAX_BYTES = 4 * 1024 * 1024
MAX_TEXT_CHARS = 2 * 1024 * 1024
EXTRACTOR_VERSION = 'local-filing-text-v1'
BLOCKS = {'p', 'div', 'br', 'hr', 'li', 'tr', 'table', 'section', 'article',
          'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'td', 'th'}
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link',
        'meta', 'param', 'source', 'track', 'wbr'}
HIDDEN = {'head', 'script', 'style', 'template', 'noscript', 'iframe', 'object',
          'embed', 'svg', 'math', 'ix:hidden', 'ix:header'}


class FilingTooLarge(ValueError):
    status_code = 413


def validate_metadata(body):
    issuer = body.get('issuer_id')
    canonical = CANONICAL_AI_SEMICONDUCTOR_UNIVERSE.get(issuer)
    cik = body.get('cik')
    if not canonical or not isinstance(cik, str) or not re.fullmatch(r'[0-9]{1,10}', cik):
        raise ValueError('FILING_ISSUER_CIK_INVALID')
    cik = cik.zfill(10)
    if cik != canonical['cik']:
        raise ValueError('FILING_ISSUER_CIK_MISMATCH')
    accession = body.get('accession')
    if not isinstance(accession, str) or not re.fullmatch(r'[0-9]{10}-[0-9]{2}-[0-9]{6}', accession):
        raise ValueError('FILING_ACCESSION_INVALID')
    # Strict whole-string allowlist: no query, credentials, port, escaping or traversal.
    origin = body.get('origin')
    pattern = (r'https://www\.sec\.gov/Archives/edgar/data/' + str(int(cik)) + '/' +
               accession.replace('-', '') + r'/[A-Za-z0-9][A-Za-z0-9_-]*\.(?:htm|html|txt)')
    if not isinstance(origin, str) or not re.fullmatch(pattern, origin):
        raise ValueError('FILING_ORIGIN_INVALID')
    if body.get('permission') not in {'USER_OWNED', 'LICENSED'}:
        raise ValueError('SOURCE_CONTENT_PERMISSION_REQUIRED')
    if body.get('format') not in {'html', 'text'}:
        raise ValueError('FILING_FORMAT_INVALID')
    if body.get('published_at') is not None:
        utc_time(body['published_at'])
    return cik


def decode_raw(encoded):
    if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_BYTES + 2) // 3):
        raise FilingTooLarge('FILING_TOO_LARGE')
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError('FILING_ENCODING_INVALID') from error
    if len(raw) > MAX_BYTES:
        raise FilingTooLarge('FILING_TOO_LARGE')
    if not raw:
        raise ValueError('SOURCE_CONTENT_MISSING')
    try:
        text = raw.decode('utf-8', errors='strict')
    except UnicodeError as error:
        raise ValueError('FILING_UTF8_REQUIRED') from error
    if any(ord(c) < 32 and c not in '\t\r\n' for c in text):
        raise ValueError('SOURCE_TEXT_INVALID')
    return raw, text


class FilingParser(HTMLParser):
    """Extract text only; never serialize markup, execute scripts or dereference URLs.

    Each emitted segment refers to exact UTF-8 byte ranges in the retained input.
    Entity segments map to their entire encoded token; block separators are synthetic.
    """
    def __init__(self, text):
        super().__init__(convert_charrefs=False)
        self.input_text = text
        self.lines = [0]
        self.lines.extend(m.end() for m in re.finditer('\n', text))
        self.byte_offsets = array('I', [0])
        for character in text:
            self.byte_offsets.append(self.byte_offsets[-1] + len(character.encode('utf-8')))
        self.stack = []
        self.parts = []
        self.segments = []
        self.length = 0

    def emit(self, value, start=None, end=None):
        if not value:
            return
        if len(self.segments) >= 50_000 or self.length + len(value) > MAX_TEXT_CHARS:
            raise ValueError('FILING_EXTRACTION_LIMIT')
        self.parts.append(value)
        self.segments.append({'start': self.length, 'end': self.length + len(value),
                              'raw_start': self.byte_offsets[start] if start is not None else None,
                              'raw_end': self.byte_offsets[end] if end is not None else None})
        self.length += len(value)

    def boundary(self):
        if self.parts and not self.parts[-1].endswith('\n'):
            self.emit('\n')

    def hidden(self):
        return bool(self.stack and self.stack[-1][1])

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        css = re.sub(r'\s+', '', attributes.get('style') or '').lower()
        hidden = (self.hidden() or tag in HIDDEN or 'hidden' in attributes or
                  (attributes.get('aria-hidden') or '').lower() == 'true' or
                  'display:none' in css or 'visibility:hidden' in css)
        if not hidden and tag in BLOCKS:
            self.boundary()
        if tag not in VOID:
            if len(self.stack) >= 128:
                raise ValueError('FILING_PARSER_DEPTH_LIMIT')
            self.stack.append((tag, hidden))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        was_hidden = self.hidden()
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break
        if not was_hidden and tag in BLOCKS:
            self.boundary()

    def position(self):
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def handle_data(self, data):
        if not self.hidden():
            start = self.position()
            self.emit(data, start, start + len(data))

    def entity(self, name, numeric=False):
        if self.hidden():
            return
        start = self.position()
        token = ('&#' if numeric else '&') + name
        if self.input_text[start + len(token):start + len(token) + 1] == ';':
            token += ';'
        self.emit(unescape(token), start, start + len(token))

    def handle_entityref(self, name):
        self.entity(name)

    def handle_charref(self, name):
        self.entity(name, numeric=True)


def preview_filing(body):
    extracted, _ = prepare_filing(body)
    return extracted


def prepare_filing(body):
    """Validate/decode once, retaining operation-local bytes for all span mappings."""
    cik = validate_metadata(body)
    raw, decoded = decode_raw(body.get('raw_base64'))
    if body['format'] == 'html':
        if re.search(r'<!\s*(?:ENTITY|DOCTYPE[^>]*\[)', decoded, re.I):
            raise ValueError('FILING_DTD_FORBIDDEN')
        parser = FilingParser(decoded)
        parser.feed(decoded)
        parser.close()
        text, segments = ''.join(parser.parts), parser.segments
    else:
        text = decoded
        if len(text) > MAX_TEXT_CHARS:
            raise ValueError('FILING_EXTRACTION_LIMIT')
        segments = [{'start': 0, 'end': len(text), 'raw_start': 0, 'raw_end': len(raw)}]
    if not text.strip():
        raise ValueError('SOURCE_CONTENT_MISSING')
    if any(ord(c) < 32 and c not in '\t\r\n' for c in text):
        raise ValueError('SOURCE_TEXT_INVALID')
    extracted = {'issuer_id': body['issuer_id'], 'cik': cik, 'accession': body['accession'],
            'origin': body['origin'], 'permission': body['permission'], 'format': body['format'],
            'text': text, 'segments': segments, 'raw_sha256': sha256(raw).hexdigest(),
            'raw_byte_length': len(raw), 'text_sha256': sha256(text.encode('utf-8')).hexdigest(),
            'extractor_version': EXTRACTOR_VERSION, 'offset_unit': 'UNICODE_CODE_POINTS',
            'raw_offset_unit': 'UTF8_BYTES', 'published_at': body.get('published_at'),
            'published_at_basis': 'USER_ASSERTED' if body.get('published_at') else 'UNKNOWN',
            'origin_validation': 'SEC_ARCHIVE_PATH_CIK_MATCH_ONLY', 'authenticity': 'NOT_VERIFIED',
            'historical_pit_proven': False, 'publication_allowed': False,
            'permission_basis': 'CALLER_DECLARED_LOCAL_RETENTION_ONLY',
            'independent_review': 'NOT_REVIEWED'}
    return extracted, raw


def raw_ranges(source, start, end):
    raw, _ = decode_raw(source['raw_base64'])
    if sha256(raw).hexdigest() != source['raw_sha256']:
        raise ValueError('FILING_RAW_HASH_MISMATCH')
    return _raw_ranges_from_validated(source, start, end, raw)


def _raw_ranges_from_validated(source, start, end, raw):
    """Internal mapping over bytes already validated by prepare_filing in this operation."""
    ranges = []
    for segment in source['segments']:
        lo, hi = max(start, segment['start']), min(end, segment['end'])
        if lo >= hi or segment['raw_start'] is None:
            continue
        a, b = segment['raw_start'], segment['raw_end']
        token = raw[a:b].decode('utf-8')
        emitted = source['text'][segment['start']:segment['end']]
        if token == emitted:
            a += len(emitted[:lo - segment['start']].encode('utf-8'))
            b = a + len(emitted[lo - segment['start']:hi - segment['start']].encode('utf-8'))
        ranges.append({'start': a, 'end': b})
    return ranges


def record_digest(source):
    return sha256(json.dumps({k: v for k, v in source.items() if k != 'record_sha256'},
                            sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                            allow_nan=False).encode('utf-8')).hexdigest()


def verify_filing(source):
    if source.get('record_sha256') != record_digest(source):
        raise ValueError('FILING_RECORD_HASH_MISMATCH')
    extracted, raw = prepare_filing(source)
    if any(source.get(key) != value for key, value in extracted.items()):
        raise ValueError('FILING_EXTRACTION_MISMATCH')
    if source['sha256'] != source['text_sha256']:
        raise ValueError('FILING_TEXT_HASH_MISMATCH')
    for evidence in source['evidence']:
        if (evidence.get('raw_sha256') != source['raw_sha256'] or
                evidence.get('text_sha256') != source['text_sha256'] or
                evidence.get('raw_ranges') != _raw_ranges_from_validated(source, evidence['start'], evidence['end'], raw)):
            raise ValueError('FILING_CITATION_BINDING_MISMATCH')
