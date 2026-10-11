"""Exact arithmetic, conservative duration matching and immutable revision selection."""
from datetime import date
from decimal import Decimal
from narrative_research_desk.causal import utc_time
from narrative_research_desk.question_scope import CONCEPT_METRICS

POLICY_VERSION = 'LATEST_FILED_PER_EXACT_CONCEPT_PERIOD_AVAILABLE_AT_CUTOFF_V1'


def calculate_change(previous, current):
    if previous is None or current is None:
        return dict(absolute_change=None, percentage_change=None, reason='MISSING_VALUE')
    previous, current = Decimal(str(previous)), Decimal(str(current))
    if not previous.is_finite() or not current.is_finite():
        raise ValueError('NON_FINITE_VALUE')
    difference = current - previous
    return dict(absolute_change=difference, percentage_change=difference / previous * 100 if previous > 0 else None,
                reason=None if previous > 0 else 'NON_POSITIVE_BASE')


def period_type(fact):
    try:
        duration = (date.fromisoformat(fact['end']) - date.fromisoformat(fact['start'])).days + 1
    except (KeyError, TypeError, ValueError):
        return None
    return 'annual' if 350 <= duration <= 380 else 'quarterly' if 75 <= duration <= 105 else None


def compare_periods(previous, current, *, operation):
    reason = None
    a, b = previous.get('metric'), current.get('metric')
    if a not in CONCEPT_METRICS or b not in CONCEPT_METRICS:
        reason = 'CONCEPT_NOT_MAPPED'
    elif CONCEPT_METRICS[a] != CONCEPT_METRICS[b]:
        reason = 'METRIC_MISMATCH'
    elif previous.get('unit') != current.get('unit') or previous.get('currency') != current.get('currency'):
        reason = 'UNIT_OR_CURRENCY_MISMATCH'
    elif not previous.get('unit') or not previous.get('currency'):
        reason = 'UNIT_OR_CURRENCY_UNKNOWN'
    elif previous.get('basis') != 'GAAP' or current.get('basis') != 'GAAP':
        reason = 'BASIS_NOT_COMPARABLE'
    elif not period_type(previous) or period_type(previous) != period_type(current):
        reason = 'PERIOD_TYPE_MISMATCH'
    else:
        start_gap = (date.fromisoformat(current['start']) - date.fromisoformat(previous['start'])).days
        end_gap = (date.fromisoformat(current['end']) - date.fromisoformat(previous['end'])).days
        if operation == 'change' and (previous['issuer_id'] != current['issuer_id'] or
                                      not 350 <= start_gap <= 380 or not 350 <= end_gap <= 380):
            reason = 'NOT_YEAR_OVER_YEAR'
        elif operation == 'compare' and (abs(start_gap) > 45 or abs(end_gap) > 45):
            reason = 'FISCAL_DATES_TOO_FAR_APART'
    result = {'status':'not_comparable' if reason else 'comparable', 'reason':reason,
              'fact_ids':[previous['fact_id'], current['fact_id']],
              'period_label':'Fiscal dates differ' if operation == 'compare' and
              (previous.get('start'),previous.get('end')) != (current.get('start'),current.get('end')) else 'Matched duration periods'}
    if not reason:
        result.update({key:format(value.normalize(), 'f') if isinstance(value, Decimal) else value
                       for key,value in calculate_change(previous.get('value'),current.get('value')).items()})
        if result['reason'] == 'MISSING_VALUE':
            result['status'] = 'not_comparable'
    return result


def select_revisions(facts, cutoff):
    groups = {}
    for fact in facts:
        try:
            if utc_time(fact['available_at']) > utc_time(cutoff):
                continue
            filed = date.fromisoformat(fact['filed'])
            if filed > utc_time(cutoff).date() or date.fromisoformat(fact['end']) > filed:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        key = tuple(fact.get(name) for name in ('issuer_id','metric','unit','currency','basis','start','end'))
        groups.setdefault(key, []).append(fact)
    selected = []
    for group in groups.values():
        latest = max(f['filed'] for f in group)
        candidates = [f for f in group if f['filed'] == latest]
        if len({str(f.get('value')) for f in candidates}) == 1:
            selected.append(sorted(candidates, key=lambda f:(f.get('accession',''),f['fact_id']))[-1])
    return selected
