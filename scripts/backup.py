"""Create a consistent SQLite backup of durable research runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from narrative_research_desk.repository import RunRepository


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    repository = RunRepository(args.database)
    try:
        report = repository.backup_to(args.output)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    finally:
        repository.close()
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
