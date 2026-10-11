"""Explicit synthetic-fixture entrypoint for local user walkthroughs."""

import json
import os
from pathlib import Path

from narrative_research_desk.api import create_app
from narrative_research_desk.service import ResearchWorkbenchService
from narrative_research_desk.sec_directory import SECCompanyDirectory


_FIXTURE = Path(os.environ.get("C2_DEMO_FIXTURE_PATH", "tests/fixtures/research/R09.json"))
_SOURCE = json.loads(_FIXTURE.read_text(encoding="utf-8"))
_LEDGER = Path(os.environ.get("C2_RUN_LEDGER_PATH", ".runtime/runs.sqlite3"))
_LEDGER.parent.mkdir(parents=True, exist_ok=True)
_SEC = Path(os.environ.get('C2_SEC_CAPTURE_DIR', 'evidence/sec-companyfacts-2026-09-24'))
_DIRECTORY = SECCompanyDirectory(os.environ.get('C2_SEC_CACHE_DIR', '.runtime/sec-cache'),
    user_agent=os.environ.get('C2_SEC_USER_AGENT', 'NarrativeResearchDesk/1.0 (https://github.com/maixuancanh)'))
app = create_app(ResearchWorkbenchService([_SOURCE], _LEDGER,
    sec_capture_dir=_SEC if _SEC.is_dir() else None, company_directory=_DIRECTORY))
