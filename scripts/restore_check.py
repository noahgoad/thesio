"""Verify a restored ledger against its expected logical state."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from narrative_research_desk.repository import RunRepository


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--expected-count", required=True, type=int)
    parser.add_argument("--expected-sha256", required=True)
    args = parser.parse_args()
    if args.expected_count < 0 or not re.fullmatch(r"[0-9a-f]{64}", args.expected_sha256):
        parser.error("EXPECTED_STATE_INVALID")
    repository = RunRepository(args.database)
    try:
        count, digest = repository.state_digest()
    finally:
        repository.close()
    report = {"run_count": count, "state_sha256": digest, "verified": count == args.expected_count and digest == args.expected_sha256}
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["verified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
