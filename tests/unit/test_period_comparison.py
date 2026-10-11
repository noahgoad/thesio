from decimal import Decimal
import pytest
from narrative_research_desk.period_comparison import calculate_change, compare_periods, select_revisions


def fact(**changes):
    return dict(fact_id='a', issuer_id='NVDA', metric='NetIncomeLoss', unit='USD', currency='USD', basis='GAAP',
                start='2024-01-01', end='2024-12-31', available_at='2026-09-24T00:00:00Z',
                filed='2025-02-01', accession='a', value='100', **changes)


def test_positive_base_growth():
    result = calculate_change(Decimal('100'), Decimal('120'))
    assert result['absolute_change'] == Decimal('20')
    assert result['percentage_change'] == Decimal('20')


@pytest.mark.parametrize('base', ['0', '-10'])
def test_nonpositive_base_has_no_percentage(base):
    result = calculate_change(Decimal(base), Decimal('12'))
    assert result['percentage_change'] is None
    assert result['reason'] == 'NON_POSITIVE_BASE'


def test_missing_is_not_zero():
    assert calculate_change(None, Decimal('12'))['absolute_change'] is None


@pytest.mark.parametrize('changes,reason', [({'unit':'EUR', 'currency':'EUR'}, 'UNIT_OR_CURRENCY_MISMATCH'),
    ({'start':'2025-10-01', 'end':'2025-12-31'}, 'PERIOD_TYPE_MISMATCH'),
    ({'start':'2026-01-01', 'end':'2026-12-31'}, 'NOT_YEAR_OVER_YEAR'),
    ({'metric':'UnknownConcept'}, 'CONCEPT_NOT_MAPPED')])
def test_incompatible_periods(changes, reason):
    current = {**fact(), 'fact_id':'b', 'start':'2025-01-01', 'end':'2025-12-31', **changes}
    result = compare_periods(fact(), current, operation='change')
    assert result['status'] == 'not_comparable'
    assert result['reason'] == reason


def test_revision_after_cutoff_excluded_and_ties_ambiguous():
    original = fact()
    revised = {**original, 'fact_id':'b', 'filed':'2026-01-01', 'available_at':'2026-10-12T00:00:00Z', 'value':'120'}
    assert select_revisions([original,revised], '2026-10-11T00:00:00Z') == [original]
    ambiguous = {**original, 'fact_id':'c', 'value':'150'}
    assert select_revisions([original,ambiguous], '2026-10-11T00:00:00Z') == []


def test_fiscal_dates_are_labeled_not_silently_equated():
    other = {**fact(), 'issuer_id':'AMD', 'fact_id':'b', 'start':'2024-02-01', 'end':'2025-01-31'}
    assert compare_periods(fact(), other, operation='compare')['period_label'] == 'Fiscal dates differ'
