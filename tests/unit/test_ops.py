from narrative_research_desk.ops import health_state
def test_health_fail_closed():
    assert health_state(1,30,0,False)["ready"]
    assert not health_state(31,30,0,False)["new_actions_allowed"]
    assert not health_state(1,30,0,True)["new_actions_allowed"]
    assert not health_state(1,30,1,False)["ready"]
