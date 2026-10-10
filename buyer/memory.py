"""What the team learned, case after case: after a case closes, a debrief subagent reads how it
went and writes one lesson; the lead researcher reads the lessons of similar cases before the
next one. Lessons are keyed on features (goal, case type, owner type, traits), never on a case or
supplier ID, and code writes every figure in them."""

import json
import logging
import statistics
import threading
from pathlib import Path

from . import llm

log = logging.getLogger("buyer")
LESSONS = Path(__file__).parent / "lessons.jsonl"  # committed: the final machine starts with them
MIN_RECALL = 3
LOCK = threading.Lock()

DEBRIEF = """You are the debrief analyst of the purchasing team of Hollerau Pumpenwerke. Below is how
one negotiation went, in shares of the supplier's quote: where we opened, our price path, its
price path, its reasons in its own words, and the score (1.0 is the best deal that was possible,
0 is no better than its first offer).
Our bidder can change four things only: how low it opens, which share of the gap to the
supplier's counter it moves per round, which kind of argument it cites first, and its tone. Code
picks all other terms. Threats, deadlines, bluffs and requests for cost data have been tested and
do not work, never suggest them.
Write the one lesson for the next negotiation with this KIND of supplier (owner type, traits,
goal): what its path and reasons show about how it concedes and when it stops, and which of the
four things to do differently, or to keep if the score is high.
Never name the supplier, the part, the case or any ID, and give no absolute prices.
Return JSON only: {"lesson": "one or two short sentences"}"""


def features(case, sides):
    return {
        "goal": case["buyer"].get("category_goal"),
        "type": case.get("type"),
        "bidders": len(sides),
        "owners": sorted({s.prof.get("owner_type") or "unknown" for s in sides}),
        "signals": sorted({k for s in sides for k in s.prof.get("signals", [])}),
    }


def path(side):
    """A thread in shares of its quote: what the debrief and the next lead can compare."""
    q = side.quote or 1.0
    return {
        "opened": round(side.ours[0] / q, 3),
        "fraction": side.fraction,
        "ours": [round(p / q, 3) for p in side.ours],
        "theirs": [round(p / q, 3) for p in side.theirs],
        "mood": side.mood,
    }


def reasons(result, sid):
    """Its reasons round by round, from the replay (practice and sandbox)."""
    out = []
    for step in result.get("trace") or []:
        if step.get("actor") == sid and step.get("reasons"):
            out.append(f"round {step.get('round')}: " + " ".join(str(r) for r in step["reasons"])[:400])
    return out


def record(case, neg, result, complete):
    """Append this case's lesson. Only a case with a score teaches (the final shows none)."""
    if result.get("score") is None:
        return None
    sides = [s for s in neg.sides.values() if s.ours]
    if not sides:
        return None
    won = neg.sides.get(result.get("supplier_id"))
    row = {
        **features(case, sides),
        "deal": bool(result.get("deal")),
        "score": round(result["score"], 3),
        "threads": [path(s) for s in ([won] if won and won.ours else sides)],
    }
    user = json.dumps({**row, "reasons": [r for s in sides for r in reasons(result, s.sid)][-12:]}, ensure_ascii=False)
    answer = llm.ask_json(complete, DEBRIEF, user) or {}
    row["lesson"] = " ".join(str(answer.get("lesson") or "").split())[:300]
    with LOCK, LESSONS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def recall(case):
    """Return one aggregate only after three distinct comparable observations.

    Generated lesson prose is intentionally excluded: it is noisy, contradictory, and can turn a
    single outcome into a strategy rule. Paths and scores are recorded facts; the aggregate is
    context, not a supplier-specific instruction.
    """
    if not LESSONS.is_file():
        return []
    rows = []
    for line in LESSONS.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    goal, kind = case["buyer"].get("category_goal"), case.get("type")
    comparable = [r for r in rows if r.get("goal") == goal and r.get("type") == kind]
    # A rerun/debrief of the same recorded outcome is not independent evidence.
    distinct = {}
    for row in comparable:
        signature = json.dumps((row.get("score"), row.get("threads")), sort_keys=True, separators=(",", ":"))
        distinct[signature] = row
    sample = list(distinct.values())
    if len(sample) < MIN_RECALL:
        return []

    threads = [row.get("threads", [{}])[0] for row in sample if row.get("threads")]
    opened = [t["opened"] for t in threads if isinstance(t.get("opened"), (int, float))]
    fractions = [t["fraction"] for t in threads if isinstance(t.get("fraction"), (int, float))]
    scores = [r["score"] for r in sample if isinstance(r.get("score"), (int, float))]
    finals = [t["theirs"][-1] for t in threads if t.get("theirs")]
    if not opened or not fractions or not scores:
        return []
    summary = (
        f"Aggregate of {len(sample)} distinct {goal}/{kind} outcomes: median opening "
        f"{statistics.median(opened):.3f} of quote, median concession fraction "
        f"{statistics.median(fractions):.2f}, median score {statistics.median(scores):.3f}"
    )
    if finals:
        summary += f", median supplier final counter {statistics.median(finals):.3f} of quote"
    return [summary + ". Treat as weak context; do not copy a single path or lesson."]
