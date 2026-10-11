from narrative_research_desk.view import render_status
def test_ui_status():
    html=render_status("STALE","FIXTURE","<script>alert(1)</script>")
    assert 'role="status"' in html and 'data-testid="mode">FIXTURE' in html and "<script>" not in html and "&lt;script&gt;" in html

def test_all_eight_statuses_are_supported():
    for state in ("EMPTY", "LOADING", "PARTIAL", "STALE", "REJECTED", "INSUFFICIENT", "COMPLETE", "ERROR"):
        assert 'data-testid="status"' in render_status(state, "FIXTURE", "source")
