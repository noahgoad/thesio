"""Small SQLite ledger primitives shared by durable repositories."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


def open_ledger(path: str | Path) -> sqlite3.Connection:
    raw_path = str(path)
    if raw_path != ":memory:":
        Path(raw_path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(raw_path, timeout=5, check_same_thread=False)
    connection.execute("PRAGMA busy_timeout=5000")
    if raw_path != ":memory:":
        connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, body TEXT NOT NULL)")
    connection.execute(
        """CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            input_hash TEXT NOT NULL,
            result_body TEXT NOT NULL,
            decision_body TEXT
        )"""
    )
    return connection


def canonical_json(body: dict[str, Any]) -> str:
    return json.dumps(body, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def put_once(connection: sqlite3.Connection, identity: str, body: dict[str, Any]) -> bool:
    encoded = canonical_json(body)
    with connection:
        found = connection.execute("SELECT body FROM records WHERE id=?", (identity,)).fetchone()
        if found:
            if found[0] != encoded:
                raise ValueError("IDENTITY_CONFLICT")
            return False
        connection.execute("INSERT INTO records(id,body) VALUES (?,?)", (identity, encoded))
    return True
