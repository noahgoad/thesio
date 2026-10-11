<p align="center"><img src="src/narrative_research_desk/static/thesio-logo.png" width="96" alt="Thesio logo"></p>

# Thesio

**Keep the question, the evidence and your conclusion together.**

Thesio is a research workspace for checking a financial story against its sources. Start with company financials, an authorized document or a guided example. Review what supports the question, what challenges it and what the available material cannot establish. Save a conclusion with the evidence behind it.

It is designed for individual researchers who want a traceable brief rather than a confident answer with no source trail. Thesio does not place trades, forecast returns or turn a saved opinion into a verified fact.

## Main capabilities

- Search companies by name or ticker and include up to eight in a research brief.
- Review supported reported figures, year-over-year changes and compatible company comparisons.
- Paste text or import an authorized text/Markdown document, then select exact supporting and challenging excerpts.
- Preview text extracted from an authorized local filing before using its quotes.
- Keep missing evidence, unsupported questions and reporting-period mismatches visible.
- Save **Supports**, **Challenges**, or **Insufficient evidence**, with selected quotes and a note.
- Reopen earlier research and export JSON or Markdown.
- Explore optional, user-authored portfolio scenarios without treating them as recommendations.
- Ask ChatGPT to help review selected evidence after a brief has been created.

## Quick start

Use Python **3.12** and run the app from the repository root. The guided example does not require an account or API key.

### Windows PowerShell

```powershell
git clone https://github.com/noahgoad/thesio.git
cd thesio
py -3.12 -m venv .venv
& .venv/Scripts/python.exe -m pip install -r requirements.lock
$env:PYTHONPATH = "$PWD/src"
& .venv/Scripts/python.exe -m uvicorn narrative_research_desk.demo:app --host 127.0.0.1 --port 8128
```

### macOS / Linux

```bash
git clone https://github.com/noahgoad/thesio.git
cd thesio
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
PYTHONPATH=src .venv/bin/python -m uvicorn narrative_research_desk.demo:app --host 127.0.0.1 --port 8128
```

Open [localhost:8128](http://127.0.0.1:8128). The Python package remains `narrative_research_desk`; the product name is Thesio.

### Walk through a research question

1. Open **Data sources** and choose **Explore the example**.
2. Ask a question, such as “Does AI spending support NVIDIA growth?”
3. Choose **Explore the evidence**.
4. Read the answer and its limitations, then inspect supporting and challenging quotes.
5. Select **Insufficient evidence**, choose the quotes behind that judgment and add a note.
6. Save the conclusion and reopen it from **Recent work**.

The example is synthetic. It illustrates how the workspace handles a question that its source cannot establish; it is not evidence about NVIDIA's actual performance.

## Choose your material

### Company financials

Thesio uses the SEC company directory and Company Facts data. The initial eight companies are suggestions, not the full search universe. A brief can include up to eight companies.

Supported questions concern reported financial measures, annual or quarterly periods, year-over-year changes and comparisons between compatible periods. A company may have no usable facts for the selected measure, currency or reporting period. Those gaps remain visible.

New analyses may retrieve company facts from fixed public SEC endpoints and cache immutable snapshots. Saved research keeps the original source snapshot rather than changing when newer data arrives. The company directory cache lasts 24 hours; the Company Facts cache lasts six hours.

SEC access depends on network availability and fair-access rules. Failed requests are reported, not replaced with made-up figures. Development-network requests have encountered HTTP 403; a working synthetic example is not proof that live SEC acquisition is available on every connection.

### Your document

Paste text or select a UTF-8 text/Markdown file. Declare the relevant storage permission and choose exact excerpts to examine. **Find relevant excerpts** proposes local text spans; you still decide which stance to assign.

A document URL is a source label, not an instruction to fetch a website. Source text, hashes and quote offsets are retained so later checks can detect changed content. A correct hash does not prove that a document is authentic or that its claims are true.

### Local filing import

The filing workflow accepts authorized local HTML/text with issuer, CIK, accession and SEC-origin information. Preview the extracted text before selecting quotes. Raw-file hashes, extracted-text hashes and byte mappings are distinct.

Publication timestamps supplied during import are user assertions. Capture time alone is not proof that a document was publicly available at an earlier date.

## From question to conclusion

Thesio separates the research request from what the source can answer. Users can review the measure, operation and reporting period before analysis. Supported facts retain their amounts, units, issuer and period context.

A causal question requires causal evidence. Choosing a revenue measure cannot establish that AI spending caused revenue growth. Ambiguous questions, unsupported periods and incomplete evidence produce an explicit gap rather than a stronger answer.

Conclusions are personal assessments attached to evidence. Revisions preserve earlier reasoning separately from the original research snapshot. Saving a conclusion does not certify source accuracy.

The main result puts the answer first. Full tables, source details, interpretation lenses and portfolio scenarios are available when needed.

## Optional portfolio scenarios

Researchers can compare two user-authored baskets with a manual portfolio. Positions may be entered directly or as CSV with the columns `issuer_id,weight`. A weight of `0.25` means 25% of portfolio value; duplicate positions are aggregated.

The workspace checks issuer/gross limits and displays concentration. The portfolio taxonomy remains limited to its original supported issuers even though the company research directory is broader.

Baskets are scenarios authored by the user. They are not optimized portfolios, return forecasts or investment recommendations. A research conclusion can be saved without creating a basket.

## ChatGPT

ChatGPT provides an optional evidence-review explanation after a research brief exists. It helps prioritize selected observations, interpretation labels and follow-up questions.

- Only selected evidence rows, citation excerpts and stored gaps enter the explanation request. Full source files and portfolio holdings are not included.
- Financial calculations, source hashes and saved conclusions are produced and maintained by the application.
- Responses must refer to supplied evidence and an allowed explanation vocabulary. Unsupported factual prose and invented figures are rejected.
- Explanations do not modify the original research result, decision history or export.
- No model request is made at startup, during ordinary analysis, when saving a conclusion or when exporting.
- If configuration is missing or a request fails, the underlying research remains available.

Credentials and model configuration must stay on the server. Before enabling this feature for private documents, consider whether selected excerpts may be processed externally.

The default local limits are 20 provider attempts per process, one concurrent request and a 32-entry memory cache. Failures consume attempts. Budgets reset on restart and are not shared across workers; they are not authenticated per-person limits.

The example works with ChatGPT disabled. Server operators must configure the optional provider before offering explanations.

## Persistence and privacy

| Data | Default location | Notes |
| --- | --- | --- |
| Research runs and conclusions | `.runtime/runs.sqlite3` | Durable SQLite records |
| Acquired SEC snapshots | `.runtime/sec-cache/` | Retained locally; not bundled in this repo |
| Form drafts and library shortcuts | Browser storage | Local to the browser; no cross-device sync |
| Document draft text | Browser storage, only if enabled | Controlled by **Remember document text on this browser** |
| Explanation cache and limits | Process memory | Reset on restart |

A registered document can be retained with its server-side research record. The browser's remember-text toggle governs the draft, not deletion of already registered source material.

Library removal affects a browser shortcut and supports undo; it does not erase the server snapshot. Uploaded files may need to be selected again when restoring an unregistered source. Storage failures are shown in the interface.

JSON and Markdown exports preserve provenance and research limitations. Integrity is checked again for source-backed operations and explanations.

## Configuration

The default example is ready to run. Useful optional environment settings include:

| Variable | Purpose |
| --- | --- |
| `C2_RUN_LEDGER_PATH` | Override the SQLite research ledger path |
| `C2_DEMO_FIXTURE_PATH` | Override the guided-example fixture file |
| `C2_SEC_CAPTURE_DIR` | Use an existing authorized Company Facts capture directory |
| `C2_SEC_CACHE_DIR` | Override the SEC cache directory |
| `C2_SEC_USER_AGENT` | Declare an appropriate application/contact identity for SEC requests |
| `C2_EXPLANATION_MAX_CALLS` | Per-process explanation attempt budget, clamped to 1–100 |
| `C2_EXPLANATION_MAX_CONCURRENCY` | Concurrent explanations, clamped to 1–4 |

Invalid numeric explanation settings fall back to safe defaults. The app does not automatically read a local `.env` file; set environment variables in the shell or your server's secret-management system.

## Architecture

```text
Browser research workspace
  → FastAPI validation and research service
  → Synthetic source / authorized document / retained SEC facts
  → Source integrity and period-compatible calculations
  → Evidence brief and explicit gaps
  → SQLite research snapshot and conclusion history
  → JSON / Markdown export
```

ChatGPT reads a bounded selection from a sealed research record through a separate optional path.

| Directory | Purpose |
| --- | --- |
| `src/narrative_research_desk/` | Research service, APIs, source checks, calculations and persistence |
| `src/narrative_research_desk/static/` | Browser logic, styles and branding |
| `src/narrative_research_desk/templates/` | Workspace HTML |
| `tests/` | Synthetic fixtures and unit/integration regressions |
| `config/`, `schemas/` | Source declarations and validation contracts |
| `scripts/` | Local backup and restore-check tools |
| `docs/` | Source boundaries and reference attribution |

The stack uses Python, FastAPI, Pydantic, SQLite, Jinja and browser JavaScript/CSS. Dependencies are pinned in `requirements.lock`.

## Testing

```powershell
$env:PYTHONPATH = "$PWD/src"
& .venv/Scripts/python.exe -m pytest -q
```

The public suite covers quote spans, financial units, source tampering, unsafe input, research conclusions, API behavior, persistence and controlled SEC responses. Synthetic regressions are not evidence of real-user effectiveness or independently verified investment results.

## Local operations and deployment boundary

`GET /healthz` checks the process. `GET /readyz` reports source ages, pause state and bounded request metrics without fetching new evidence or invoking ChatGPT.

A local operator can obtain a token from `GET /api/operator-token` and use `POST /api/pause` with a matching origin. Pausing stops new work; already accepted operations may finish. This is an operational control, not user authentication.

The bundled configuration is a local workspace, not an authenticated multi-tenant service. Keep it on loopback for sensitive documents. Shared hosting requires access control, tenant separation, persistent storage, document retention policies and deployment-wide abuse limits.

Backup and restore-check helpers live in `scripts/`; use `--help` to inspect their required arguments. Backups may contain private research and must not be committed.

## Limitations and attribution

Missing opposing evidence does not confirm a thesis. Quote labels are annotations, structured financial facts do not establish causality, and internal hash consistency is not independent source verification.

This repository excludes local documents, research databases, retained external response bodies and development recordings. It makes no claim of validated trading performance or independent acceptance certification.

See [SOURCES](docs/SOURCES.md) and [REUSE](docs/REUSE.md) for source boundaries and reference acknowledgments. Third-party material remains subject to its original permissions.

**Thesio supports research judgment. It does not replace it.**

