#!/usr/bin/env python3
# ABOUTME: Status-line printer for prompt-squeeze — reads totals.json and emits compact status string.
# ABOUTME: Plug into Claude Code's status-line config: `python3 .../status_line.py`.

from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import rollup  # noqa: E402

TOTALS_PATH = Path.home() / ".claude" / "prompt-squeeze" / "totals.json"
LOG_PATH = Path.home() / ".claude" / "prompt-squeeze" / "log.jsonl"


def main() -> int:
    totals = None
    # Prefer the cached totals.json (fast). Fall back to live computation if missing.
    if TOTALS_PATH.is_file():
        try:
            totals = json.loads(TOTALS_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            totals = None
    if totals is None:
        totals = rollup.compute_totals(LOG_PATH)
    print(rollup.format_status_line(totals))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
