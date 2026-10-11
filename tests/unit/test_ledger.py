from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from narrative_research_desk.ledger import open_ledger, put_once
from narrative_research_desk.repository import RunRepository


def test_idempotent_ledger(tmp_path):
    connection = open_ledger(tmp_path / "case.sqlite")
    assert put_once(connection, "one", {"status": "proposed"})
    assert not put_once(connection, "one", {"status": "proposed"})
    with pytest.raises(ValueError, match="IDENTITY_CONFLICT"):
        put_once(connection, "one", {"status": "filled"})
    connection.close()


def test_run_writers_are_serialized_and_conflicting_input_is_rejected(tmp_path):
    path = tmp_path / "runs.sqlite"
    repositories = [RunRepository(path) for _ in range(6)]
    try:
        with ThreadPoolExecutor(max_workers=len(repositories)) as pool:
            inserted = list(pool.map(lambda repo: repo.put_once("same", "a" * 64, {"run_id": "same"}), repositories))
        assert sum(inserted) == 1
        with pytest.raises(ValueError, match="RUN_ID_CONFLICT"):
            repositories[0].put_once("same", "b" * 64, {"run_id": "same"})
        assert repositories[0].get("same")["input_hash"] == "a" * 64
    finally:
        for repository in repositories:
            repository.close()


def test_failed_insert_rolls_back_without_partial_run(tmp_path):
    repository = RunRepository(tmp_path / "runs.sqlite")
    try:
        repository.connection.execute(
            "CREATE TRIGGER reject_run BEFORE INSERT ON runs BEGIN SELECT RAISE(ABORT, 'injected'); END"
        )
        with pytest.raises(sqlite3.IntegrityError, match="injected"):
            repository.put_once("retryable", "a" * 64, {"run_id": "retryable"})
        assert repository.get("retryable") is None
        repository.connection.execute("DROP TRIGGER reject_run")
        assert repository.put_once("retryable", "a" * 64, {"run_id": "retryable"})
    finally:
        repository.close()
