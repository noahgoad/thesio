"""Local relevant excerpts; source content is data and relevance never assigns stance."""
from hashlib import sha256
import re

WORDS = {'revenue':r'revenue|sales|doanh thu', 'net_income':r'net income|net profit|profitability|lợi nhuận',
         'capex':r'capex|capital expenditure|property.{0,20}equipment'}


def suggest_quotes(text, *, issuer_id, metric, keywords=()):
    pattern = WORDS.get(metric)
    if pattern is None:
        raise ValueError('SCOPE_METRIC_INVALID')
    if keywords:
        pattern += '|' + '|'.join(re.escape(word) for word in keywords if word.strip())
    digest = sha256(text.encode('utf-8')).hexdigest()
    result = []
    boundaries = [m.end() for m in re.finditer(r'\n+|[.!?]+(?=\s|$)',text)] + [len(text)]
    previous = 0
    for boundary in boundaries:
        chunk = text[previous:boundary]
        quote = chunk.strip()
        if quote and len(quote) <= 8000 and re.search(pattern,quote,re.I):
            start = previous + len(chunk) - len(chunk.lstrip())
            result.append(dict(label='Relevant excerpt', issuer_id=issuer_id, metric=metric, start=start,
                               end=start+len(quote), quote=quote, source_sha256=digest))
        if len(result) == 8:
            break
        previous = boundary
    return result


def validate_suggestion(text, suggestion):
    if sha256(text.encode('utf-8')).hexdigest() != suggestion['source_sha256']:
        raise ValueError('SOURCE_CHANGED')
    start,end = suggestion['start'],suggestion['end']
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text) or text[start:end] != suggestion['quote']:
        raise ValueError('QUOTE_OFFSET_INVALID')
    return True
