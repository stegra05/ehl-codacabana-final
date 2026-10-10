"""JSON-lines logs under logs/: every plan, every move and every finished case, for the practice
analysis and the pitch."""

import json
import threading
from datetime import UTC, datetime
from pathlib import Path

MOVES = Path("logs/moves.jsonl")
CASES = Path("logs/cases.jsonl")
PLANS = Path("logs/plans.jsonl")
_lock = threading.Lock()


def _append(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(
        {"ts": datetime.now(UTC).isoformat(timespec="seconds"), **record}, ensure_ascii=False, default=str
    )
    with _lock, path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def move(record):
    _append(MOVES, record)


def case(record):
    _append(CASES, record)


def plan(record):
    _append(PLANS, record)
