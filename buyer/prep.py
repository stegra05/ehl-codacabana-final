"""The preparation agent: the model reads the case briefing and looks things up in the data
package itself (SQL, ID lookup, documents) before the session opens, then proposes a stance per
supplier: what it values, which arguments to lead with, how much of the room to capture, how deep
to open, how much patience to show, the tone, and an assessment in words for the e-mails.

Code clamps every figure to a band around the computed plan (`briefing.plan`) and goes on with the
plan alone when the model is late, broken or silent. The loop runs before the session opens, so no
supplier clock is running; it still has a hard wall-clock budget because the wave's cap is."""

import json
import logging
import re
import time

from . import llm

log = logging.getLogger("buyer")
BUDGET_S = 25.0  # wall clock for the whole loop per case
STEP_S = 12.0  # one model answer
MAX_STEPS = 6  # lookups before the stance is due
MAX_ROWS = 25
BANDS = {"capture_delta": (-0.15, 0.15), "opening_gap_delta": (-0.05, 0.08), "patience": (0.15, 1.0)}
CLAIM_KINDS = (
    "should_cost", "order_history", "index", "rival", "notice", "forecast", "scorecard", "hedged", "open_book",
)  # fmt: skip
TOOLS_RE = re.compile(r"\{.*\}", re.S)

SYSTEM = """You are the preparation analyst of the purchasing team of Hollerau Pumpenwerke, a German
pump maker. A buyer agent is about to negotiate the case below by e-mail with the suppliers listed.
Your job: read the briefing, look up what matters in our data package, and hand the buyer a stance
per supplier.

Answer every turn with exactly ONE JSON object and nothing else:
- {"query": "SELECT ..."}      one read-only SQL statement over the package (tables below, at most
                                 25 rows come back)
- {"lookup": "<id>"}           the fact behind a citable ID (doc:, news:, ctr:, quote:, sc:, cost:, ...)
- {"document": "<id>"}         the text of a letter, call note or news item
- {"stance": {"<supplier_id>": {...}, ...}}   your final answer, one entry per supplier

A stance entry:
  "assessment": 2 to 3 sentences in words for the person writing the e-mails: who this supplier is
                to us, what it values, what to acknowledge. No figures, no IDs.
  "values": what it wants from us, from the data (e.g. "faster payment", "a firm volume",
            "a long contract", "its lead time", "planning security"), 1 to 4 items
  "lead_with": the kinds of argument to use first, from: should_cost, order_history, index, rival,
               notice, forecast, scorecard, hedged, open_book
  "capture_delta": -0.15 to 0.15, how much more (+) or less (-) of the possible saving to go for
                   than the plan: + when the data shows it usually moves or has spare capacity,
                   - when it is frozen, fully booked, selling near cost or walks away easily
  "opening_gap_delta": -0.05 to 0.08, how much deeper (+) or shallower (-) to open than the plan
  "patience": 0.15 to 1.0, the cumulative gap it will tolerate (low for touchy suppliers)
  "tone": "warm" or "firm"
  "risks": up to 3 short items

Use at most a few lookups: its letters and call notes, its scorecard, our payment behaviour, its
negotiation record, other quotes for the part. Then answer with the stance. Be quick."""


def tools_text(pkg):
    if pkg is None:
        return "No data package: answer with the stance right away."
    try:
        tables = pkg.tables()
    except Exception:  # noqa: BLE001 - no SQLite
        return "The package has no SQL tables; use lookup and document only."
    return "TABLES:\n" + "\n".join(f"- {t}: {', '.join(c.split()[0] for c in m['columns'])}" for t, m in tables.items())


def case_text(case, brief):
    b = case["buyer"]
    econ = brief.get("economics") or {}
    cons = brief.get("constraints") or {}
    lines = [
        f"CASE {case['case_id']}: {case.get('title')}",
        f"BRIEFING: {case.get('briefing')}",
        f"TYPE {case.get('type')}, GOAL {b.get('category_goal')}, SUPPLIERS {', '.join(case.get('suppliers') or [])}",
        f"PARTS {', '.join(case.get('parts') or [])}",
        f"NEGOTIABLE {cons.get('negotiable')}; OPTIONS {json.dumps(cons.get('options'))}",
        f"FIXED {json.dumps(cons.get('fixed'))}; MUST-HAVES {json.dumps(cons.get('must_haves'))}",
        f"NEED {econ.get('need_per_year')} a year over {econ.get('horizon_years')} years; current price "
        f"{econ.get('current_unit_price')}; fallback price {econ.get('fallback_unit_price')}; "
        f"alternative {econ.get('alternative')}; C of the alternative {econ.get('c_alt')}",
        f"REFS {', '.join(case.get('refs') or [])}",
    ]
    for part, m in (brief.get("market") or {}).items():
        lines.append(f"MARKET {part}: quotes {json.dumps(m.get('quotes'))[:600]}")
        lines.append(f"  prices {json.dumps(m.get('prices'))[:400]}")
        lines.append(f"  should-cost {json.dumps(m.get('should_cost'))[:400]}")
        lines.append(f"  drivers {json.dumps(m.get('drivers'))[:400]}")
    return "\n".join(lines)


def execute(pkg, call):
    """One tool call of the model, as text for the next turn. Read-only by construction."""
    if pkg is None:
        return "no data package"
    try:
        if "query" in call:
            rows = pkg.query(str(call["query"]), (), MAX_ROWS)
            return json.dumps(rows, ensure_ascii=False, default=str)[:4000]
        if "lookup" in call:
            return json.dumps(pkg.lookup(str(call["lookup"])), ensure_ascii=False, default=str)[:2000]
        if "document" in call:
            return pkg.document(str(call["document"]))[:3000]
    except Exception as e:  # noqa: BLE001 - a bad SQL statement is the model's problem, not the move's
        return f"error: {e}"
    return "unknown call: answer with query, lookup, document or stance"


def parse(text):
    m = TOOLS_RE.search(text or "")
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def clamp(stance, suppliers):
    """Only known suppliers, every figure inside its band, every list of known words."""
    out = {}
    for sid in suppliers:
        s = stance.get(sid) if isinstance(stance, dict) else None
        if not isinstance(s, dict):
            continue
        c = {"assessment": " ".join(str(s.get("assessment") or "").split())[:600]}
        for k, (lo, hi) in BANDS.items():
            try:
                c[k] = round(min(hi, max(lo, float(s[k]))), 3)
            except (KeyError, TypeError, ValueError):
                pass
        c["values"] = [str(v)[:60] for v in (s.get("values") or []) if v][:4]
        c["lead_with"] = [k for k in (s.get("lead_with") or []) if k in CLAIM_KINDS][:4]
        c["risks"] = [str(v)[:80] for v in (s.get("risks") or []) if v][:3]
        c["tone"] = s.get("tone") if s.get("tone") in ("warm", "firm") else None
        if llm.FORBIDDEN.search(c["assessment"]):
            c["assessment"] = ""  # figures or leaks: the e-mails do without it
        out[sid] = c
    return out


def run(complete, case, pkg, brief, budget_s=BUDGET_S):
    """{supplier_id: stance} from the model's loop, or {} without a model, on a timeout or on
    anything unexpected. Never raises."""
    if complete is None:
        return {}
    t0 = time.monotonic()
    transcript = [case_text(case, brief), tools_text(pkg), "Answer with your first JSON object."]
    steps = []
    try:
        for _ in range(MAX_STEPS + 1):
            left = budget_s - (time.monotonic() - t0)
            if left < llm.MIN_S:
                break
            text = llm.POOL.submit(complete, SYSTEM, "\n\n".join(transcript)).result(timeout=min(STEP_S, left))
            call = parse(text)
            if call is None:
                transcript.append("Your last answer was not one JSON object. Answer with the stance now.")
                continue
            if "stance" in call:
                stance = clamp(call["stance"], case.get("suppliers") or [])
                took = time.monotonic() - t0
                log.info(
                    "%s prep: stance for %s in %.1fs after %d lookups", case["case_id"], list(stance), took, len(steps)
                )
                return {"stance": stance, "steps": steps, "took_s": round(time.monotonic() - t0, 1)}
            result = execute(pkg, call)
            steps.append({"call": call, "result": result[:300]})
            transcript += [f"YOU: {json.dumps(call)}", f"RESULT: {result}"]
            if len(steps) >= MAX_STEPS:
                transcript.append("No more lookups: answer with the stance now.")
    except Exception as e:  # noqa: BLE001 - a slow or broken model must not cost the case
        log.warning("%s prep: no stance after %.1fs: %s", case["case_id"], time.monotonic() - t0, e)
    return {"stance": {}, "steps": steps, "took_s": round(time.monotonic() - t0, 1)}
