from narrative_research_desk.question_scope import parse_scope
from narrative_research_desk.research_brief import build_brief


def observation(metric='NetIncomeLoss', **changes):
    return {**dict(fact_id=metric, issuer_id='NVDA', metric=metric, unit='USD', currency='USD', basis='GAAP',
        start='2025-01-01', end='2025-12-31', value='120', filed='2026-02-01', accession='synthetic',
        available_at='2026-09-24T00:00:00Z'), **changes}


def test_metric_changes_brief_and_all_claims_have_evidence():
    facts = [observation(), observation('Revenues', value='200')]
    profit = build_brief(parse_scope('Net income', ['NVDA']), facts, '2026-10-11T00:00:00Z')
    revenue = build_brief(parse_scope('Revenue', ['NVDA']), facts, '2026-10-11T00:00:00Z')
    assert profit['status'] == revenue['status'] == 'answered'
    assert profit['claims'][0]['fact_ids'] == ['NetIncomeLoss']
    assert revenue['claims'][0]['fact_ids'] == ['Revenues']
    assert profit['summary'] != revenue['summary']


def test_causal_and_missing_company_are_insufficient():
    for scope in [parse_scope('Did AI cause revenue growth?', ['NVDA']), parse_scope('Revenue', ['AMD'])]:
        result = build_brief(scope, [observation('Revenues')], '2026-10-11T00:00:00Z')
        assert result['status'] == 'insufficient'
        assert result['claims'] == []


def test_change_requires_yoy_and_binds_calculation():
    current = observation('Revenues')
    previous = observation('Revenues', fact_id='prior', value='100', start='2024-01-01', end='2024-12-31')
    result = build_brief(parse_scope('Revenue growth', ['NVDA']), [current, previous], '2026-10-11T00:00:00Z')
    assert result['claims'][0]['kind'] == 'calculated'
    assert result['claims'][0]['fact_ids'] == ['prior', 'Revenues']
    assert result['comparisons'][0]['percentage_change'] == '20'
