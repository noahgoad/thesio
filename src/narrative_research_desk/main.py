"""Production entrypoint; starts without fixture or network sources."""

import os
from pathlib import Path

from narrative_research_desk.api import create_app
from narrative_research_desk.service import ResearchWorkbenchService

ledger_path = Path(os.environ.get("C2_RUN_LEDGER_PATH", str(Path.cwd() / ".runtime" / "runs.sqlite3")))
sec_capture_dir = os.environ.get('C2_SEC_CAPTURE_DIR')
app = create_app(ResearchWorkbenchService([], ledger_path=ledger_path, sec_capture_dir=sec_capture_dir))
