"""Conservative local question suggestions; explicit controls keep text intact."""
from dataclasses import asdict, dataclass
import re

METRIC_CONCEPTS = {
    'revenue': ('RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues'),
    'net_income': ('NetIncomeLoss',),
    'capex': ('PaymentsToAcquirePropertyPlantAndEquipment',),
}
# Including assessed taxes is deliberately not interchangeable with net revenue.
CONCEPT_METRICS = {concept: metric for metric, concepts in METRIC_CONCEPTS.items() for concept in concepts}


@dataclass(frozen=True)
class ResearchScope:
    issuer_ids: list[str]
    metric: str | None
    operation: str
    period_request: str
    needs_confirmation: bool

    def to_dict(self):
        return asdict(self)


def parse_scope(question, issuer_ids, *, metric=None, operation=None, period_request=None):
    text = question.lower().strip()
    matches = [name for name, pattern in (
        ('revenue', r'\brevenue\b|\bsales\b|doanh thu'),
        ('net_income', r'net income|net profit|profitability|lợi nhuận'),
        ('capex', r'capex|capital expenditure|property.{0,20}equipment')) if re.search(pattern, text)]
    if metric is not None and metric not in METRIC_CONCEPTS:
        raise ValueError('SCOPE_METRIC_INVALID')
    if operation is not None and operation not in {'level', 'change', 'compare'}:
        raise ValueError('SCOPE_OPERATION_INVALID')
    if period_request is not None and period_request not in {'annual', 'quarterly', 'latest'}:
        raise ValueError('SCOPE_PERIOD_INVALID')
    selected = metric or (matches[0] if len(matches) == 1 else None)
    op = operation or ('compare' if re.search(r'compare|versus|\bvs\b', text) else
                       'change' if re.search(r'change|growth|grew|increas|decreas|\bris(?:e|en|ing)\b|\brose\b|\bfall(?:en|ing)?\b|\bfell\b|year.over.year|\byoy\b', text) else 'level')
    period = period_request or ('quarterly' if re.search(r'quarter|\bq[1-4]\b', text) else 'annual')
    causal = bool(re.search(r'\bwhy\b|caus|\bdrove\b|\bdriv(?:e|es|ing)\b|\battribut|\bbecause\b|\bimpact\b|\beffect\b|\bsupport\b|\bforecast\b|\bpredict\b', text))
    unsupported_period = bool(re.search(r'(?<!\d)(?:19|20)\d{2}(?!\d)|\bq[1-4]\b|\bttm\b|month|last year|last quarter', text))
    unsupported_operation = bool(re.search(r'quarter[\s-]+(?:on|over)[\s-]+quarter|\bq\s*/\s*q\b|\bqoq\b|sequential|\bcagr\b|\bper\b|margin|ratio|\badjusted\b|non.gaap|percentage of|percent of|\bmedian\b|\baverage\b', text))
    generic_profit = bool(re.search(r'\bprofits?\b|profitability',text)) and not bool(re.search(r'net income|net profits?',text))
    ambiguous = selected is None or len(matches) > 1 or generic_profit
    return ResearchScope(list(issuer_ids), selected, op, period, causal or unsupported_period or unsupported_operation or ambiguous)
