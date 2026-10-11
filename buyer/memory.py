"""What the team learned, case after case: after a case closes, a debrief subagent reads how it
went and writes one lesson; the lead researcher reads what we did in similar cases and what came
of it before the next one (the figures, not the lesson: one run is a data point). Rows are keyed on
features (goal, case type, owner type, traits), never on a case or supplier ID, and code writes
every figure in them."""

import json
import logging
import threading
from pathlib import Path

from . import llm

log = logging.getLogger("buyer")
LESSONS = Path(__file__).parent / "lessons.jsonl"  # committed: the final machine starts with them
RECALL = 5
LOCK = threading.Lock()

DEBRIEF = """You are the debrief analyst of the purchasing team of Hollerau Pumpenwerke. Below is how
one negotiation went, in shares of the supplier's quote: where we opened, our price path, its
price path, its reasons in its own words, and the score (1.0 is the best deal that was possible,
0 is no better than its first offer).
Our team can change four things only: which terms it offers as a trade next to its main proposal,
which kind of argument it cites first, how it answers the supplier's arguments, and its tone.
Code sets the prices and the pace. Threats, deadlines, bluffs and requests for cost data have been tested and
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
        "ours": [round(p / q, 3) for p in side.ours],
        "theirs": [round(p / q, 3) for p in side.theirs],
        "tactics": side.tactics,
        "trades": [f"{t['field']}={t['value']}" for t in side.trades],
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


def recall(case, n=RECALL):
    """The latest runs of the most similar cases (same goal, then same case type), as lines: what
    we did and what came of it. The debrief's lesson stays in the file: it is one run's story, and
    the lead would read it as a rule."""
    if not LESSONS.is_file():
        return []
    rows = []
    for line in LESSONS.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    goal, kind = case["buyer"].get("category_goal"), case.get("type")
    ranked = sorted(enumerate(rows), key=lambda r: ((r[1].get("goal") == goal) + (r[1].get("type") == kind), r[0]))
    out = []
    for _, r in ranked[-n:]:
        if r.get("goal") != goal and r.get("type") != kind:
            continue
        t = (r.get("threads") or [{}])[0]
        out.append(
            f"{r.get('goal')} {r.get('type')}, {r.get('bidders')} bidder(s), owner {'/'.join(r.get('owners') or [])}, "
            f"traits {r.get('signals')}: opened at {t.get('opened')} of the quote, offered trades "
            f"{t.get('trades') or []}, its prices {t.get('theirs')}, score {r.get('score')}."
        )
    return out
