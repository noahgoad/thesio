"""Evidence-linked local templates. No causal or investment inference."""
from itertools import combinations
from decimal import Decimal
from narrative_research_desk.issuer_gate import CANONICAL_AI_SEMICONDUCTOR_UNIVERSE
from narrative_research_desk.question_scope import METRIC_CONCEPTS
from narrative_research_desk.period_comparison import compare_periods, period_type, select_revisions, POLICY_VERSION

COMPARISON_REASONS = {
    'FISCAL_DATES_TOO_FAR_APART':'Reporting periods start or end too far apart.',
    'PERIOD_TYPE_MISMATCH':'The observations have different reporting durations, such as quarterly and annual.',
    'UNIT_OR_CURRENCY_MISMATCH':'The observations use different units or currencies.',
    'UNIT_OR_CURRENCY_UNKNOWN':'The observation unit or currency is missing.',
    'BASIS_NOT_COMPARABLE':'The accounting definitions have not been shown to match.',
    'CONCEPT_NOT_MAPPED':'The reported concept has no verified comparison mapping.',
    'METRIC_MISMATCH':'The observations measure different financial items.',
    'NOT_YEAR_OVER_YEAR':'The periods are not matching year-over-year observations.',
    'MISSING_VALUE':'A reported value is missing.',
}


def build_brief(scope, facts, cutoff, *, company_names=None):
    result = dict(schema_version='brief_v1', status='insufficient', scope=scope.to_dict(), summary='',
                  claims=[], comparisons=[], gaps=[], next_steps=[],
                  method='Deterministic local templates over retained facts; no causal inference. Local capture availability only.',
                  policy_version=POLICY_VERSION, cutoff=cutoff, evidence_rows=[])
    if scope.needs_confirmation:
        result['gaps'].append('This question exceeds the supported scope or is ambiguous. Choose one financial measure and operation; causal and specific-date questions need additional evidence.')
    else:
        eligible = [f for f in select_revisions(facts, cutoff) if f.get('metric') in METRIC_CONCEPTS.get(scope.metric, ())
                    and f.get('value') is not None and f.get('unit') == 'USD' and f.get('basis') == 'GAAP'
                    and period_type(f) and (scope.period_request == 'latest' or period_type(f) == scope.period_request)]
        selected = {}
        for issuer in scope.issuer_ids:
            company = [f for f in eligible if f['issuer_id'] == issuer]
            if not company:
                result['gaps'].append(f'{issuer}: no eligible {scope.metric} facts for the selected period and cutoff.')
                continue
            end = max(f['end'] for f in company)
            latest = [f for f in company if f['end'] == end]
            if len({(f['start'],f['metric'],f['value']) for f in latest}) != 1:
                result['gaps'].append(f'{issuer}: competing concepts or durations require source review.')
                continue
            selected[issuer] = latest[0]
        label = (scope.metric or '').replace('_',' ')
        def money(value):
            amount = Decimal(value)
            for divisor,name in [(Decimal('1000000000000'),'trillion'),(Decimal('1000000000'),'billion'),(Decimal('1000000'),'million')]:
                if abs(amount) >= divisor:
                    return f"${amount/divisor:,.2f} {name} USD"
            return f"${amount:,.2f} USD"
        def name(f):
            if company_names and f['issuer_id'] in company_names:
                return company_names[f['issuer_id']]
            return CANONICAL_AI_SEMICONDUCTOR_UNIVERSE.get(f['issuer_id'],{}).get('legal_name',f['issuer_id'])
        def reported(f):
            return f"{name(f)} reported {label} of {money(f['value'])} for {f['start']} to {f['end']}."
        def add_claim(text, kind, rows, calculation_id=None):
            result['claims'].append(dict(text=text, kind=kind, fact_ids=[f['fact_id'] for f in rows], calculation_id=calculation_id))
            known = {f['fact_id'] for f in result['evidence_rows']}
            result['evidence_rows'].extend(f for f in rows if f['fact_id'] not in known)
        if scope.operation == 'level':
            for f in selected.values():
                add_claim(reported(f), 'reported', [f])
        elif scope.operation == 'change':
            for issuer, current in selected.items():
                prior = [f for f in eligible if f['issuer_id'] == issuer and f['end'] < current['end'] and
                         compare_periods(f,current,operation='change')['status'] == 'comparable']
                if len(prior) != 1:
                    result['gaps'].append(f'{issuer}: no unique comparable prior-year observation. Adjacent periods are not automatically YoY.')
                    continue
                previous = prior[0]
                calculation = compare_periods(previous,current,operation='change')
                calculation['calculation_id'] = f"yoy:{previous['fact_id']}:{current['fact_id']}"
                result['comparisons'].append(calculation)
                percent = f" ({Decimal(calculation['percentage_change']):,.2f}%)" if calculation['percentage_change'] is not None else ' (percentage omitted: non-positive base)'
                calculation['formula'] = 'current − previous; percentage = difference / positive previous × 100'
                text = reported(previous) + ' ' + reported(current) + f" Absolute change: {money(calculation['absolute_change'])}{percent}."
                add_claim(text,'calculated',[previous,current],calculation['calculation_id'])
        elif scope.operation == 'compare':
            if len(scope.issuer_ids) < 2:
                result['gaps'].append('Select at least two companies to compare.')
            for a,b in combinations(selected.values(),2):
                calculation = compare_periods(a,b,operation='compare')
                calculation['calculation_id'] = f"compare:{a['fact_id']}:{b['fact_id']}"
                result['comparisons'].append(calculation)
                if calculation['status'] != 'comparable':
                    result['gaps'].append(f"{name(a)} and {name(b)}: {COMPARISON_REASONS.get(calculation['reason'],'Comparison compatibility has not been established.')}")
                else:
                    calculation['formula'] = f"{b['issuer_id']} − {a['issuer_id']}"
                    add_claim(reported(a)+' '+reported(b)+f" Difference ({name(b)} − {name(a)}): {money(calculation['absolute_change'])}. {calculation['period_label']}.",
                              'calculated',[a,b],calculation['calculation_id'])
    result['status'] = ('partial' if result['gaps'] else 'answered') if result['claims'] else 'insufficient'
    result['summary'] = ' '.join(c['text'] for c in result['claims']) or 'The available evidence cannot answer this question within the selected scope.'
    if result['gaps']:
        result['next_steps'] = ['Review the scope and reporting periods.', 'Add an authorized document for missing evidence.']
    return result
