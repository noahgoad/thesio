"""Deterministic research workflow over explicitly registered source documents."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from typing import Any
from uuid import uuid4
from pathlib import Path
from datetime import datetime, timezone

from narrative_research_desk.basket import research_basket
from narrative_research_desk.causal import utc_time
from narrative_research_desk.citations import verify_citation
from narrative_research_desk.export import export_report
from narrative_research_desk.ranking import rank_research
from narrative_research_desk.repository import RunRepository
from narrative_research_desk.source_registry import register_source
from narrative_research_desk.primary_sources import RetainedSEC, SOURCE_ID
from narrative_research_desk.portfolio import compare_portfolio
from narrative_research_desk.filings import prepare_filing, _raw_ranges_from_validated, record_digest, verify_filing
from narrative_research_desk.question_scope import parse_scope
from narrative_research_desk.research_brief import build_brief


class ResearchServiceError(Exception):
    def __init__(self, status_code: int, code: str):
        self.status_code = status_code
        self.code = code
        super().__init__(code)


class ResearchWorkbenchService:
    """Registered example and supplied-text research with durable local state."""

    def __init__(self, source_documents: list[dict[str, Any]], ledger_path: str | Path = ":memory:", *, sec_capture_dir: str | Path | None = None, company_directory=None):
        self.sources: dict[str, dict[str, Any]] = {}
        self.sec = RetainedSEC(sec_capture_dir) if sec_capture_dir else None
        self.company_directory = company_directory
        self.repository = RunRepository(ledger_path)
        for item in source_documents:
            source = item.get("source", {})
            text = source.get("text")
            if not isinstance(text, str) or not text:
                raise ValueError("SOURCE_CONTENT_MISSING")
            registered = register_source(
                source.get("source_id"), text.encode("utf-8"), source.get("origin"),
                source.get("permission"), source.get("captured_at"), role="FIXTURE_DATA",
            )
            facts = deepcopy(item.get("facts", []))
            for fact in facts:
                if isinstance(fact.get("quality_flags"), list):
                    fact["quality_flags"] = [
                        flag for flag in fact["quality_flags"]
                        if flag not in {"SPAN_VERIFIED", "GAAP_VERIFIED", "NON_GAAP_VERIFIED"}
                    ]
            self.sources[source["source_id"]] = {**source, **registered, "text": text, "facts": facts, "narratives": deepcopy(item.get("narratives", []))}

    @staticmethod
    def _canonical(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)

    def _sec_reader(self, source_id):
        if source_id == SOURCE_ID:
            return self.sec
        if self.company_directory and isinstance(source_id, str) and source_id.startswith('sec-selection-'):
            return self.company_directory.reader(source_id)
        return None

    @staticmethod
    def _public(result: dict[str, Any]) -> dict[str, Any]:
        return {key: deepcopy(value) for key, value in result.items() if not key.startswith("_")}

    def ingest(self, body: dict[str, Any]) -> dict[str, Any]:
        text = body["text"]
        if not text.strip():
            raise ValueError("SOURCE_CONTENT_MISSING")
        if any(ord(char) < 32 and char not in "\t\r\n" for char in text):
            raise ValueError("SOURCE_TEXT_INVALID")
        payload = text.encode("utf-8")
        if len(payload) > 1_000_000:
            raise ResearchServiceError(413, "SOURCE_TOO_LARGE")
        if body["permission"] not in {"USER_OWNED", "LICENSED"}:
            raise ValueError("SOURCE_CONTENT_PERMISSION_REQUIRED")
        if not body["origin"].strip():
            raise ValueError("SOURCE_INCOMPLETE")
        captured = datetime.now(timezone.utc).isoformat()
        source_id = "supplied-" + str(uuid4())
        source = {**register_source(source_id, payload, body["origin"], body["permission"], captured),
                  "text": text, "mode": "USER_SUPPLIED", "available_at": captured,
                  "provenance_status": "USER_ASSERTED_ORIGIN", "evidence": []}
        for index, evidence in enumerate(body.get("evidence", [])):
            start = evidence.get("start")
            if start is None:
                start = text.find(evidence["quote"])
            citation = {"source_id": source_id, "source_sha256": source["sha256"],
                        "start": start, "end": start + len(evidence["quote"]), "quote": evidence["quote"]}
            verified = verify_citation(citation, {source_id: source}, set())
            source["evidence"].append({**deepcopy(evidence), **citation, **verified, "citation_id": f"quote-{index}"})
        self.repository.put_source(source)
        return {key: deepcopy(value) for key, value in source.items() if key not in {"text", "evidence"}}

    def _analyze_supplied(self, source: dict[str, Any], request: dict[str, Any], run_id: str, input_hash: str) -> dict[str, Any]:
        if source.get('source_id') != request['source_id']:
            raise ValueError('SOURCE_LOOKUP_ID_MISMATCH')
        filing_required = request['source_id'].startswith('filing-') or source.get('kind') == 'LOCAL_FILING'
        if filing_required:
            verify_filing(source)
            if source.get('kind') != 'LOCAL_FILING':
                raise ValueError('FILING_SOURCE_KIND_MISMATCH')
        if utc_time(source["available_at"]) > utc_time(request["cutoff"]):
            raise ResearchServiceError(422, "SOURCE_AFTER_CUTOFF")
        if sha256(source["text"].encode("utf-8")).hexdigest() != source["sha256"]:
            raise ValueError("SOURCE_HASH_MISMATCH")
        citations = [deepcopy(item) for item in source["evidence"] if item["issuer_id"] in request["watchlist"]]
        if not citations:
            raise ValueError("NO_EVIDENCE_FOR_WATCHLIST")
        for item in citations:
            verify_citation(item, {source["source_id"]: source}, set())
        evidence_status = {stance: "FOUND" if any(item["stance"] == stance for item in citations) else "NOT_FOUND" for stance in ("support", "challenge")}
        unknowns = ["The origin and source accuracy are user asserted; exact quotes do not validate the claims.",
                    "Support/challenge labels are supplied by the user, not independently adjudicated.",
                    "This document alone does not establish causality, valuation, accounting basis, or future returns."]
        for stance, status in evidence_status.items():
            if status == "NOT_FOUND":
                unknowns.append(f"No {stance} quote was supplied for the selected issuers. Absence is not confirmation.")
        uncovered = sorted(set(request["watchlist"]) - {item["issuer_id"] for item in citations})
        if uncovered:
            unknowns.append("No supplied quotes cover: " + ", ".join(uncovered))
        narratives = [{"narrative_id": stance, "title": "Support interpretation" if stance == "support" else "Challenge interpretation",
                       "thesis": "User-labeled quotes " + ("support" if stance == "support" else "challenge") + " the question; review their context before choosing.",
                       "classification": "USER_INTERPRETATION", "citation_ids": [item["citation_id"] for item in citations if item["stance"] == stance]}
                      for stance in ("support", "challenge") if evidence_status[stance] == "FOUND"]
        result = {"run_id": run_id, "input_hash": input_hash, "source_id": source["source_id"], "source_sha256": source["sha256"],
                  "cutoff": request["cutoff"], "mode": "USER_SUPPLIED", "question": request["question"].strip(), "watchlist": list(request["watchlist"]),
                  "status": "COMPLETE" if all(status == "FOUND" for status in evidence_status.values()) and not uncovered else "INSUFFICIENT",
                  "narratives": narratives, "baskets": [], "citations": citations, "counterevidence_status": [], "evidence_status": evidence_status,
                  "decision": None, "unknowns": unknowns, "search_coverage": "SUPPLIED_DOCUMENT_ONLY", "provenance_status": source["provenance_status"],
                  "source_document": deepcopy(source)}
        self._add_brief(result, request)
        if filing_required:
            result['filing_run_sha256'] = self._filing_run_digest(result)
        self.repository.put_once(run_id, input_hash, result)
        return result

    def ingest_filing(self, body: dict[str, Any]) -> dict[str, Any]:
        extracted, raw = prepare_filing(body)
        captured = datetime.now(timezone.utc).isoformat()
        source_id = 'filing-' + str(uuid4())
        source = {**extracted, 'source_id': source_id, 'kind': 'LOCAL_FILING',
                  'sha256': extracted['text_sha256'], 'raw_base64': body['raw_base64'],
                  'mode': 'USER_SUPPLIED', 'captured_at': captured, 'available_at': captured,
                  'availability_basis': 'LOCAL_IMPORT_ONLY',
                  'provenance_status': 'USER_ASSERTED_ORIGIN', 'evidence': []}
        for index, item in enumerate(body.get('evidence', [])):
            if item['issuer_id'] != source['issuer_id']:
                raise ValueError('FILING_EVIDENCE_ISSUER_MISMATCH')
            quote = item['quote']
            start = item.get('start')
            if start is None:
                start = source['text'].find(quote)
                if start >= 0 and source['text'].find(quote, start + 1) >= 0:
                    raise ValueError('FILING_QUOTE_AMBIGUOUS_REQUIRE_OFFSET')
            citation = {'source_id': source_id, 'source_sha256': source['sha256'],
                        'text_sha256': source['text_sha256'], 'raw_sha256': source['raw_sha256'],
                        'start': start, 'end': start + len(quote), 'quote': quote}
            verified = verify_citation(citation, {source_id: source}, set())
            source['evidence'].append({**deepcopy(item), **citation, **verified,
                                      'raw_ranges': _raw_ranges_from_validated(source, start, start + len(quote), raw),
                                      'citation_id': f'quote-{index}', 'adjudication': 'USER_LABELED_NOT_VERIFIED'})
        source['record_sha256'] = record_digest(source)
        self.repository.put_source(source)
        return {key: deepcopy(value) for key, value in source.items()
                if key not in {'raw_base64', 'text', 'segments', 'evidence'}}

    def _filing_run_digest(self, result):
        # Decisions are stored separately and can change only through explicit user input.
        body = {key: value for key, value in result.items() if key not in {'decision', 'filing_run_sha256', 'user_conclusion', 'conclusion_history'}}
        return sha256(self._canonical(body).encode('utf-8')).hexdigest()

    def _verify_filing_run(self, result):
        # RunRepository.get restores input_hash from its dedicated SQLite column,
        # independent of mutable result_body. Bind identity before any mode/kind branch.
        fields = ('source_id', 'cutoff', 'mode', 'question', 'watchlist')
        inputs = {key: result.get(key) for key in fields}
        if 'research_scope' in result:
            inputs['research_scope'] = result['research_scope']
        expected = sha256(self._canonical(inputs).encode('utf-8')).hexdigest()
        if expected != result['input_hash']:
            identity = {'parent_run_id': result.get('parent_run_id'),
                        'positions': result.get('positions'), 'baskets': result.get('baskets'),
                        'comparison_policy': 'REPLACE_60_PERCENT_SLEEVE_V1'}
            if (not isinstance(identity['parent_run_id'], str) or
                    sha256(self._canonical(identity).encode('utf-8')).hexdigest() != result['input_hash']):
                raise ValueError('RUN_INPUT_HASH_MISMATCH')
            parent = self.read(identity['parent_run_id'])
            if any(result.get(key) != parent.get(key) for key in (*fields, 'source_sha256')):
                raise ValueError('RUN_PARENT_SOURCE_MISMATCH')
        # Verify a saved result seal before consulting any mutable snapshot discriminator.
        seal = result.get('filing_run_sha256')
        if seal is not None and seal != self._filing_run_digest(result):
            raise ValueError('FILING_RUN_HASH_MISMATCH')
        source_id = result.get('source_id', '')
        retained = self.repository.get_source(source_id)
        filing_required = (source_id.startswith('filing-') or
                           (retained is not None and retained.get('kind') == 'LOCAL_FILING') or
                           seal is not None)
        if not filing_required:
            return
        if seal is None:
            raise ValueError('FILING_RUN_HASH_MISSING')
        if retained is None:
            raise ValueError('FILING_RETAINED_SOURCE_MISSING')
        snapshot = result.get('source_document', {})
        # Exact snapshot equality lets one validated extraction cover both copies.
        # A changed snapshot is rejected, never substituted or repaired from retained data.
        if retained != snapshot:
            raise ValueError('FILING_SNAPSHOT_MISMATCH')
        verify_filing(retained)
        if (retained.get('kind') != 'LOCAL_FILING' or retained != snapshot or
                result['source_sha256'] != retained['text_sha256']):
            raise ValueError('FILING_SNAPSHOT_MISMATCH')
        for citation in result['citations']:
            verify_citation(citation, {result['source_id']: retained}, set())
            if citation not in retained['evidence']:
                raise ValueError('FILING_CITATION_BINDING_MISMATCH')

    def analyze(self, request: dict[str, Any]) -> dict[str, Any]:
        source_id = request.get("source_id")
        mode = request.get("mode")
        sec = self._sec_reader(source_id) if mode == 'PUBLIC_READ' else None
        if mode not in {"FIXTURE", "USER_SUPPLIED"} and not (mode == "PUBLIC_READ" and sec):
            raise ResearchServiceError(503, "MODE_PROVIDER_NOT_CONFIGURED")
        question = request.get("question", "").strip()
        watchlist = request.get("watchlist", [])
        if not question or not watchlist or len(set(watchlist)) != len(watchlist):
            raise ResearchServiceError(422, "QUESTION_OR_WATCHLIST_INVALID")
        run_id = request.get("run_id") or str(uuid4())
        input_body = {"source_id": source_id, "cutoff": request["cutoff"], "mode": mode, "question": question, "watchlist": watchlist}
        existing = self.repository.get(run_id)
        # Old identities use their original five fields; only new runs bind parsed scope.
        if not existing or 'research_scope' in existing:
            input_body['research_scope'] = self._scope(request).to_dict()
        input_hash = sha256(self._canonical(input_body).encode("utf-8")).hexdigest()
        if existing:
            if existing["input_hash"] != input_hash:
                raise ResearchServiceError(409, "RUN_ID_CONFLICT")
            self._verify_filing_run(existing)
            return deepcopy(existing)

        if mode == 'PUBLIC_READ':
            retained = sec.read(watchlist, request['cutoff'], include_history=True)
            policy = {'version': 'C2_RETAINED_SEC_PORTFOLIO_V1', 'selection': 'LATEST_END_PER_EXACT_CONCEPT_RETAIN_REVISIONS',
                      'availability': 'LOCAL_CAPTURE_ONLY', 'basket_budget': '0.6', 'issuer_cap': '0.25',
                      'scenario': 'REPLACE_60_PERCENT_SLEEVE', 'taxonomy': 'CANONICAL_ISSUER_TAXONOMY_V1'}
            result = {**retained, 'run_id': run_id, 'input_hash': input_hash, 'source_id': source_id,
                'source_sha256': retained['manifest_sha256'], 'mode': mode, 'question': question,
                'watchlist': watchlist, 'cutoff': request['cutoff'], 'status': 'INSUFFICIENT',
                'facts_policy': 'LATEST_END_PER_EXACT_CONCEPT_RETAIN_ALL_ACCESSIONS_AND_START_DATES',
                'research_policy': policy, 'config_sha256': sha256(self._canonical(policy).encode()).hexdigest(),
                'narratives': [
                    {'narrative_id': 'financial-context', 'title': 'Financial context lens',
                     'thesis': 'Review revenue, net income and cash purchases of property/equipment. Do these facts support your thesis?',
                     'classification': 'REVIEW_QUESTION'},
                    {'narrative_id': 'risk-gaps', 'title': 'Risk and missing evidence lens',
                     'thesis': 'Review differences in period, revisions and missing metrics. What additional evidence could invalidate your thesis?',
                     'classification': 'REVIEW_QUESTION'}],
                'baskets': [], 'citations': [], 'counterevidence_status': ['NOT_FOUND'], 'decision': None,
                'search_coverage': 'RETAINED_SEC_STRUCTURED_API_ONLY',
                'unknowns': ['No adjudicated narrative, counter thesis, AI segment attribution or causal conclusion is provided.',
                    'Hash/pointer verification binds the retained API observation; it does not verify original filing text spans.',
                    'Availability is conservatively the capture time. Filing dates are date-only; published_at is unknown. No historical PIT claim.',
                    'Captures may be stale; see each source capture time. Latest-end selection is per exact concept; periods are not interchangeable.',
                    'METADATA_ONLY: local structured summaries retain provenance; raw SEC bodies are excluded from export and release.',
                    'Values have not been independently adjudicated as factual gold. Research choices do not establish accuracy.']}
            result['companies'] = [{'ticker': issuer, 'name': sec.issuers[issuer]['legal_name'],
                                    'cik': sec.issuers[issuer]['cik']} for issuer in watchlist]
            self._add_brief(result, request)
            self.repository.put_once(run_id, input_hash, result)
            return result

        source = self.repository.get_source(source_id) or self.sources.get(source_id)
        if source is None:
            raise ResearchServiceError(404, "SOURCE_NOT_FOUND")
        if (source.get("mode") == "USER_SUPPLIED") != (mode == "USER_SUPPLIED"):
            raise ValueError("SOURCE_MODE_MISMATCH")
        if mode == "USER_SUPPLIED":
            return self._analyze_supplied(source, request, run_id, input_hash)
        try:
            if utc_time(source["available_at"]) > utc_time(request["cutoff"]):
                raise ResearchServiceError(422, "SOURCE_AFTER_CUTOFF")
        except KeyError as error:
            raise ResearchServiceError(422, "SOURCE_PROVENANCE_INCOMPLETE") from error

        fact_by_id = {fact["fact_id"]: fact for fact in source["facts"]}
        narratives = []
        citations = []
        scores = {}
        verified_claims = []
        for card in source["narratives"]:
            fact = fact_by_id.get(card.get("fact_id"))
            if fact is None or fact.get("issuer_id") not in watchlist:
                continue
            quote = card["quote"]
            start = source["text"].find(quote)
            citation = {
                "source_id": source_id,
                "source_sha256": source["sha256"],
                "start": start,
                "end": start + len(quote),
                "quote": quote,
                "counter_fact_id": card.get("counter_fact_id"),
            }
            verified = verify_citation(citation, {source_id: source}, set(fact_by_id))
            score = rank_research({key: card[key] for key in ("quality", "relevance", "recency", "conflict")})["score"]
            scores[card["narrative_id"]] = score
            narratives.append({
                "narrative_id": card["narrative_id"], "title": card["title"], "thesis": card["thesis"],
                "fact": fact, "research_score": score, "classification": "RESEARCH_PRIORITY",
                "citation_id": f"citation-{card['narrative_id']}",
                "counter_fact_status": verified["counter_fact_status"],
                "limitation": "Fixture research priority only; not a return forecast or trading signal.",
            })
            citations.append({
                "citation_id": f"citation-{card['narrative_id']}",
                "quote": quote,
                "source_sha256": source["sha256"],
                "start": start,
                "end": start + len(quote),
                **verified,
            })
            verified_claims.append({"claim_id": card["narrative_id"], "material": True, "citation": citation})

        if len(narratives) != 2:
            raise ResearchServiceError(422, "TWO_NARRATIVES_REQUIRED")
        baskets = [{
            "narrative_id": narrative["narrative_id"],
            "weights": research_basket({issuer: narrative["research_score"] if issuer == narrative["fact"]["issuer_id"] else 0.0 for issuer in watchlist}),
            "budget_fraction": 0.6,
        } for narrative in narratives]
        result = {
            "run_id": run_id, "input_hash": input_hash, "source_id": source_id,
            "source_sha256": source["sha256"], "cutoff": request["cutoff"], "mode": mode,
            "question": question, "watchlist": list(watchlist), "status": "COMPLETE",
            "narratives": narratives, "baskets": baskets, "citations": citations,
            "counterevidence_status": [item["counter_fact_status"] for item in narratives],
            "decision": None, "_citation_sources": {source_id: source},
            "_material_claims": verified_claims, "_fact_ids": list(fact_by_id),
        }
        try:
            self._add_brief(result, request)
            self.repository.put_once(run_id, input_hash, self._public(result))
        except ValueError as error:
            code = str(error)
            status = 409 if code in {"RUN_ID_CONFLICT", "RUN_RESULT_CONFLICT"} else 422
            raise ResearchServiceError(status, code) from error
        return result

    @staticmethod
    def _scope(request):
        return parse_scope(request['question'],request['watchlist'],metric=request.get('metric'),
                           operation=request.get('operation'),period_request=request.get('period_request'))

    def _add_brief(self, result, request):
        scope = self._scope(request)
        result['research_scope'] = scope.to_dict()
        result['conclusion_schema_version'] = 2
        result['brief'] = build_brief(scope, result.get('fact_history',result.get('facts',[])),request['cutoff'],
                                      company_names={c['ticker']: c['name'] for c in result.get('companies', [])})
        if result.get('mode') == 'USER_SUPPLIED':
            result['brief']['quote_evidence'] = [{key:deepcopy(c[key]) for key in ('citation_id','quote','issuer_id','stance','start','end','source_sha256')}
                                                for c in result['citations']]
            result['brief']['summary'] = (f"{len(result['citations'])} exact document quotes are available for review. "
                'Their supporting or challenging labels are your annotations. The quotes do not provide validated financial amounts or establish causality.')

    def read(self, run_id: str) -> dict[str, Any]:
        run = self.repository.get(run_id)
        if run is None:
            raise ResearchServiceError(404, "RUN_NOT_FOUND")
        self._verify_filing_run(run)
        conclusions = self.repository.conclusions(run_id)
        if conclusions:
            run['user_conclusion'] = conclusions[-1]
            run['conclusion_history'] = conclusions
        return deepcopy(run)

    def conclude(self, run_id, decision):
        self.read(run_id)
        try:
            return self.repository.conclude(run_id,decision)
        except ValueError as error:
            raise ResearchServiceError(409 if str(error) == 'DECISION_CONFLICT' else 422,str(error)) from error

    def portfolio(self, run_id: str, request: dict[str, Any]) -> dict[str, Any]:
        parent = self.read(run_id)
        baskets, comparison = compare_portfolio(parent, request)
        identity = {'parent_run_id': run_id, 'positions': request['positions'], 'baskets': baskets,
                    'comparison_policy': 'REPLACE_60_PERCENT_SLEEVE_V1'}
        digest = sha256(self._canonical(identity).encode()).hexdigest()
        revision_id = 'portfolio-' + digest
        existing = self.repository.get(revision_id)
        if existing:
            return existing
        result = {**parent, 'run_id': revision_id, 'parent_run_id': run_id, 'input_hash': digest,
                  'positions': deepcopy(request['positions']), 'baskets': baskets,
                  'portfolio_comparison': comparison, 'decision': None}
        result.pop('user_conclusion', None)
        result.pop('conclusion_history', None)
        if 'filing_run_sha256' in parent:
            result['filing_run_sha256'] = self._filing_run_digest(result)
        self.repository.put_once(revision_id, digest, result)
        return result

    def choose(self, run_id: str, decision: dict[str, Any]) -> dict[str, Any]:
        try:
            self.read(run_id)
            return self.repository.choose(run_id, decision)
        except KeyError as error:
            raise ResearchServiceError(404, "RUN_NOT_FOUND") from error
        except ValueError as error:
            code = str(error)
            status = 409 if code == "DECISION_CONFLICT" else 422
            raise ResearchServiceError(status, code) from error

    def backup_to(self, destination: str | Path) -> dict[str, Any]:
        return self.repository.backup_to(destination)

    def ledger_state_digest(self) -> tuple[int, str]:
        return self.repository.state_digest()

    def close(self) -> None:
        self.repository.close()

    def export(self, run_id: str, format: str = 'json') -> dict[str, Any]:
        result = self.read(run_id)
        hashes = [result['source_sha256']]
        if result['mode'] == 'PUBLIC_READ':
            sec = self._sec_reader(result['source_id'])
            if not sec:
                raise ValueError('LOCAL_SOURCE_UNAVAILABLE')
            sec.verify(result)
            hashes += [source['sha256'] for source in result['source_refs']]
        if result["mode"] == "USER_SUPPLIED":
            source = result["source_document"]
            if sha256(source["text"].encode("utf-8")).hexdigest() != result["source_sha256"]:
                raise ValueError("SOURCE_HASH_MISMATCH")
            for citation in result["citations"]:
                verify_citation(citation, {result["source_id"]: source}, set())
            if source.get('kind') == 'LOCAL_FILING':
                hashes.append(source['raw_sha256'])
                hashes.append(source['record_sha256'])
                # Download is a local research brief, never an authorization to publish raw filings.
                result['source_document'].pop('raw_base64', None)
        return export_report("C2", result, hashes, format=format)
