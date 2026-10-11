"""Decimal portfolio weights and evidence-bound, user-authored replacement scenarios."""
from decimal import Decimal, InvalidOperation
from narrative_research_desk.issuer_gate import CANONICAL_AI_SEMICONDUCTOR_UNIVERSE as CANONICAL_ISSUERS

BUDGET = Decimal('0.6')
CAP = Decimal('0.25')


def weight(value):
    if isinstance(value, bool):
        raise ValueError('WEIGHT_INVALID')
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError('WEIGHT_INVALID')
    if not number.is_finite() or number < 0 or number > 1:
        raise ValueError('WEIGHT_INVALID')
    return number


def text(value):
    return format(value.normalize(), 'f')


def summary(weights):
    sectors = {}
    for issuer, value in weights.items():
        sector = CANONICAL_ISSUERS[issuer]['sector']
        sectors[sector] = sectors.get(sector, Decimal(0)) + value
    return {'issuer_weights': {k: text(v) for k, v in sorted(weights.items())},
            'sector_weights': {k: text(v) for k, v in sorted(sectors.items())},
            'cash': text(1 - sum(weights.values(), Decimal(0))),
            'warnings': [f'ISSUER_CAP:{k}' for k, v in sorted(weights.items()) if v > CAP] +
                        [f'SECTOR_CAP:{k}' for k, v in sorted(sectors.items()) if v > BUDGET]}


def compare_portfolio(run, request):
    current = {}
    for row in request['positions']:
        issuer = row['issuer_id']
        if issuer not in CANONICAL_ISSUERS:
            raise ValueError('POSITION_MAPPING')
        current[issuer] = current.get(issuer, Decimal(0)) + weight(row['weight'])
    if sum(current.values(), Decimal(0)) > 1:
        raise ValueError('PORTFOLIO_GROSS')
    cards = {card['narrative_id'] for card in run['narratives']}
    baskets = request['baskets']
    if len(baskets) != 2 or {b['narrative_id'] for b in baskets} != cards or len(cards) != 2:
        raise ValueError('TWO_DISTINCT_BASKETS_REQUIRED')
    evidence = {}
    for fact in run.get('facts', []):
        evidence.setdefault(fact['issuer_id'], []).append(fact['fact_id'])
    for citation in run.get('citations', []):
        if citation.get('issuer_id'):
            evidence.setdefault(citation['issuer_id'], []).append(citation['citation_id'])
    if run['mode'] == 'FIXTURE':
        for card in run['narratives']:
            evidence.setdefault(card['fact']['issuer_id'], []).append(card['citation_id'])
    output, scenarios = [], []
    for basket in baskets:
        weights = {issuer: weight(value) for issuer, value in basket['weights'].items()}
        if any(value > CAP for value in weights.values()):
            raise ValueError('BASKET_ISSUER_CAP')
        if any(issuer not in run['watchlist'] or issuer not in evidence for issuer, value in weights.items() if value > 0):
            raise ValueError('BASKET_EVIDENCE_MISSING')
        if any(issuer not in CANONICAL_ISSUERS for issuer in weights):
            raise ValueError('POSITION_MAPPING')
        gross = sum(weights.values(), Decimal(0))
        if gross > BUDGET:
            raise ValueError('BASKET_GROSS_CAP')
        mapped = {k: text(v) for k, v in sorted(weights.items()) if v > 0}
        output.append({'narrative_id': basket['narrative_id'], 'weights': {**mapped, 'CASH': text(1-gross)},
            'budget_fraction': text(BUDGET), 'gross': text(gross), 'classification': 'USER_AUTHORED_RESEARCH_ALLOCATION',
            'rationale': basket.get('rationale', ''), 'invalidation_condition': basket.get('invalidation_condition', ''),
            'evidence_refs': {issuer: sorted(set(evidence[issuer])) for issuer in mapped},
            'limitation': 'References provide issuer context, not evidence that this allocation is optimal or that the thesis is true.'})
        projected = {issuer: current.get(issuer, Decimal(0)) * (1-BUDGET) + weights.get(issuer, Decimal(0))
                     for issuer in current.keys() | weights.keys()}
        scenarios.append({'narrative_id': basket['narrative_id'], **summary(projected),
            'overlap_issuers': sorted(k for k in weights if weights[k] > 0 and current.get(k, 0) > 0)})
    comparison = {'scenario_policy': 'REPLACE_60_PERCENT_SLEEVE', 'budget_fraction': text(BUDGET),
        'formula': 'scenario issuer weight = 0.4 * current issuer weight + basket issuer weight; remainder is cash',
        'current': summary(current), 'scenarios': scenarios, 'mapping_basis': 'CANONICAL_ISSUER_TAXONOMY_V1',
        'position_provenance': 'USER_ASSERTED_MANUAL_WEIGHTS', 'execution': 'NO_LIVE',
        'limitations': ['Weights are fractions of total portfolio value, not shares or notionals.',
                        'Sector classification is a frozen research taxonomy; no correlation or price data are inferred.']}
    return output, comparison
