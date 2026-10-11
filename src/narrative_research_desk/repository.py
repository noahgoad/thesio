"""Durable, idempotent storage for research runs and separate user decisions."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Any

from narrative_research_desk.ledger import canonical_json, open_ledger


class RunRepository:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self.connection = open_ledger(path)
        self._lock = RLock()
        with self.connection:
            self.connection.execute("CREATE TABLE IF NOT EXISTS research_sources (source_id TEXT PRIMARY KEY, body TEXT NOT NULL)")
            # Do not backfill legacy rows: their current body is not trusted baseline evidence.
            self.connection.execute("CREATE TABLE IF NOT EXISTS research_run_integrity (run_id TEXT PRIMARY KEY, result_sha256 TEXT NOT NULL)")
            self.connection.execute('CREATE TABLE IF NOT EXISTS research_conclusions (run_id TEXT NOT NULL, decision_id TEXT NOT NULL, revision INTEGER NOT NULL, body TEXT NOT NULL, PRIMARY KEY(run_id,decision_id), UNIQUE(run_id,revision))')
            self.connection.execute('CREATE TABLE IF NOT EXISTS research_conclusion_integrity (run_id TEXT NOT NULL, decision_id TEXT NOT NULL, body_sha256 TEXT NOT NULL, run_sha256 TEXT NOT NULL, PRIMARY KEY(run_id,decision_id))')
            # Additive protection for newly saved legacy choices; never seal old bodies on read/retry.
            self.connection.execute('CREATE TABLE IF NOT EXISTS research_decision_integrity (run_id TEXT PRIMARY KEY, body_sha256 TEXT NOT NULL, run_sha256 TEXT NOT NULL)')

    @staticmethod
    def _validate_decision(run_id, result, decision):
        if (not isinstance(decision, dict) or not set(decision) <= {'narrative_id','note','run_id'} or
                not isinstance(decision.get('narrative_id'), str) or not 1 <= len(decision['narrative_id']) <= 128 or
                not isinstance(decision.get('note',''), str) or len(decision.get('note','')) > 1000 or
                decision.get('run_id',run_id) != run_id or
                decision['narrative_id'] not in {item['narrative_id'] for item in result.get('narratives', [])}):
            raise ValueError('DECISION_INVALID')

    def conclusions(self, run_id):
        with self._lock:
            rows = self.connection.execute('SELECT c.body,i.body_sha256,i.run_sha256 FROM research_conclusions c LEFT JOIN research_conclusion_integrity i ON c.run_id=i.run_id AND c.decision_id=i.decision_id WHERE c.run_id=? ORDER BY c.revision', (run_id,)).fetchall()
            raw = self.connection.execute('SELECT result_body FROM runs WHERE run_id=?',(run_id,)).fetchone()
        for body,body_digest,run_digest in rows:
            if body_digest != sha256(body.encode()).hexdigest() or raw is None or run_digest != sha256(raw[0].encode()).hexdigest():
                raise ValueError('CONCLUSION_INTEGRITY_MISMATCH')
        return [json.loads(row[0]) for row in rows]

    def conclude(self, run_id, decision):
        with self._lock, self.connection:
            self.connection.execute('BEGIN IMMEDIATE')
            run = self.get(run_id)
            if run is None:
                raise KeyError('RUN_NOT_FOUND')
            if decision.get('version') != 2 or decision.get('verdict') not in {'supports','challenges','insufficient'}:
                raise ValueError('CONCLUSION_INVALID')
            ids = decision.get('evidence_ids', [])
            valid = {f['fact_id'] for f in run.get('facts', []) + run.get('fact_history', [])}
            valid.update(c['citation_id'] for c in run.get('citations', []))
            if len(ids) != len(set(ids)) or not set(ids) <= valid:
                raise ValueError('EVIDENCE_NOT_IN_RUN')
            if not ids and (decision['verdict'] != 'insufficient' or not decision.get('note','').strip()):
                raise ValueError('CONCLUSION_EVIDENCE_OR_NOTE_REQUIRED')
            history = self.conclusions(run_id)
            existing = next((d for d in history if d['decision_id'] == decision['decision_id']), None)
            if existing:
                if any(existing.get(key) != value for key,value in decision.items()):
                    raise ValueError('DECISION_CONFLICT')
                return existing
            record = {**decision, 'run_id':run_id, 'revision':len(history)+1,
                      'supersedes':history[-1]['decision_id'] if history else None}
            self.connection.execute('INSERT INTO research_conclusions VALUES (?,?,?,?)',
                (run_id,record['decision_id'],record['revision'],canonical_json(record)))
            raw = self.connection.execute('SELECT result_body FROM runs WHERE run_id=?',(run_id,)).fetchone()[0]
            self.connection.execute('INSERT INTO research_conclusion_integrity VALUES (?,?,?,?)',
                (run_id,record['decision_id'],sha256(canonical_json(record).encode()).hexdigest(),sha256(raw.encode()).hexdigest()))
        return record

    def put_source(self, source: dict[str, Any]) -> None:
        with self._lock, self.connection:
            self.connection.execute("INSERT INTO research_sources(source_id,body) VALUES (?,?)", (source["source_id"], canonical_json(source)))

    def get_source(self, source_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self.connection.execute("SELECT body FROM research_sources WHERE source_id=?", (source_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def close(self) -> None:
        with self._lock:
            self.connection.close()

    def put_once(self, run_id: str, input_hash: str, result: dict[str, Any]) -> bool:
        result_body = canonical_json(result)
        with self._lock, self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            existing = self.connection.execute(
                "SELECT input_hash, result_body FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if existing is not None:
                if existing[0] != input_hash:
                    raise ValueError("RUN_ID_CONFLICT")
                if existing[1] != result_body:
                    raise ValueError("RUN_RESULT_CONFLICT")
                return False
            self.connection.execute(
                "INSERT INTO runs(run_id,input_hash,result_body,decision_body) VALUES (?,?,?,NULL)",
                (run_id, input_hash, result_body),
            )
            self.connection.execute(
                'INSERT INTO research_run_integrity(run_id,result_sha256) VALUES (?,?)',
                (run_id, sha256(result_body.encode('utf-8')).hexdigest()),
            )
        return True

    def get(self, run_id: str, *, require_integrity: bool = False) -> dict[str, Any] | None:
        with self._lock:
            row = self.connection.execute(
                'SELECT r.input_hash,r.result_body,r.decision_body,i.result_sha256,d.body_sha256,d.run_sha256 '
                'FROM runs r LEFT JOIN research_run_integrity i ON r.run_id=i.run_id '
                'LEFT JOIN research_decision_integrity d ON r.run_id=d.run_id WHERE r.run_id=?', (run_id,)
            ).fetchone()
        if row is None:
            return None
        if require_integrity and row[3] is None:
            raise ValueError('RUN_RESULT_UNSEALED')
        if row[3] is not None and sha256(row[1].encode('utf-8')).hexdigest() != row[3]:
            raise ValueError('RUN_RESULT_HASH_MISMATCH')
        result = json.loads(row[1])
        if row[3] is None and (str(result.get('source_id', '')).startswith('filing-') or
                              'filing_run_sha256' in result or
                              result.get('source_document', {}).get('kind') == 'LOCAL_FILING'):
            raise ValueError('RUN_RESULT_UNSEALED_LEGACY_FILING')
        if row[4] is not None and (row[2] is None or sha256(row[2].encode()).hexdigest() != row[4] or
                                  sha256(row[1].encode()).hexdigest() != row[5]):
            raise ValueError('DECISION_INTEGRITY_MISMATCH')
        try:
            decision = json.loads(row[2]) if row[2] is not None else None
        except (ValueError, TypeError):
            raise ValueError('DECISION_INVALID') from None
        if row[2] is not None:
            self._validate_decision(run_id, result, decision)
        result["input_hash"] = row[0]
        result["decision"] = decision
        return result

    def state_digest(self) -> tuple[int, str]:
        with self._lock:
            rows = self.connection.execute(
                "SELECT run_id,input_hash,result_body,decision_body FROM runs ORDER BY run_id"
            ).fetchall()
        digest = sha256(canonical_json({"rows": [list(row) for row in rows]}).encode("utf-8")).hexdigest()
        return len(rows), digest

    def choose(self, run_id: str, decision: dict[str, Any]) -> dict[str, Any]:
        encoded = canonical_json(decision)
        with self._lock, self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            self.get(run_id)  # checksum check inside the write transaction, before mutating decisions
            row = self.connection.execute(
                "SELECT result_body,decision_body FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if row is None:
                raise KeyError("RUN_NOT_FOUND")
            result = json.loads(row[0])
            if decision.get("narrative_id") not in {item["narrative_id"] for item in result.get("narratives", [])}:
                raise ValueError("NARRATIVE_NOT_IN_RUN")
            self._validate_decision(run_id, result, decision)
            if row[1] is not None:
                if json.loads(row[1]) != decision:
                    raise ValueError("DECISION_CONFLICT")
                return json.loads(row[1])
            self.connection.execute(
                "UPDATE runs SET decision_body=? WHERE run_id=?", (encoded, run_id)
            )
            self.connection.execute('INSERT INTO research_decision_integrity VALUES (?,?,?)',
                (run_id,sha256(encoded.encode()).hexdigest(),sha256(row[0].encode()).hexdigest()))
        return json.loads(encoded)

    def backup_to(self, destination: str | Path) -> dict[str, Any]:
        target_path = Path(destination)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.resolve() == Path(self.path).resolve():
            raise ValueError("BACKUP_TARGET_IS_SOURCE")
        if target_path.exists():
            raise FileExistsError("BACKUP_TARGET_EXISTS")
        target = sqlite3.connect(str(target_path), timeout=5)
        try:
            with self._lock:
                self.connection.backup(target)
        finally:
            target.close()
        verified = open_ledger(target_path)
        try:
            rows = verified.execute(
                "SELECT run_id,input_hash,result_body,decision_body FROM runs ORDER BY run_id"
            ).fetchall()
            state = [list(row) for row in rows]
            digest = sha256(canonical_json({"rows": state}).encode("utf-8")).hexdigest()
        finally:
            verified.close()
        return {"path": str(target_path), "run_count": len(rows), "state_sha256": digest}
