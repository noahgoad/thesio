from narrative_research_desk.question_scope import parse_scope


def test_supported_metric_and_operation():
    scope = parse_scope('How has net income changed year over year?', ['NVDA'])
    assert scope.metric == 'net_income'
    assert scope.operation == 'change'
    assert scope.period_request == 'annual'
    assert not scope.needs_confirmation


def test_causal_and_unknown_questions_need_confirmation():
    for question in ['Did AI cause revenue growth?', 'What changed?', 'What is the share price?']:
        assert parse_scope(question, ['NVDA']).needs_confirmation


def test_explicit_selection_does_not_claim_causal_answer():
    scope = parse_scope('Why did revenue grow?', ['AMD'], metric='revenue', operation='level')
    assert scope.needs_confirmation
    assert scope.issuer_ids == ['AMD']


def test_scope_does_not_hide_unsupported_period_or_multiple_metrics():
    assert parse_scope('Revenue in 2020', ['NVDA']).needs_confirmation
    assert parse_scope('Revenue and net income', ['NVDA']).needs_confirmation
    assert parse_scope('Compare reported revenue and profit', ['NVDA','AMD']).needs_confirmation
    assert parse_scope('Revenue and net income', ['NVDA'],metric='revenue').needs_confirmation


def test_unsupported_operation_ratio_and_fiscal_year_are_not_answered():
    for text in ['How did net income change quarter over quarter?', 'net income per employee',
                 'net income margin', 'Revenue in FY2025', 'Revenue CAGR', 'Revenue per share']:
        assert parse_scope(text,['NVDA']).needs_confirmation, text


def test_change_verbs_and_all_qoq_spellings():
    for text in ['How much did net income increase?', 'Net income decreased', 'Revenue rose', 'Revenue fell']:
        assert parse_scope(text,['NVDA']).operation == 'change', text
    for phrase in ['quarter-on-quarter','quarter on quarter','quarter-over-quarter','quarter over quarter','q/q']:
        assert parse_scope(phrase+' net income growth',['NVDA']).needs_confirmation
