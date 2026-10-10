"""Export every saved session into flat, machine-readable tables for later analysis.

Run: uv run python analysis/export.py   (reads logs/sessions/, logs/cases/, data/package; writes exports/)

  sessions.csv / .jsonl   one row per session: case, outcome, C open/deal/alt/best, deal terms, cost breakdown
  threads.csv  / .jsonl   one row per supplier thread: what the data says about the supplier, what it did
  messages.jsonl          one row per e-mail, both directions: terms with C, status, claims, reasons, back office
  claims.csv              one row per data argument we made, with the arena's check
  findings.json           the curated lessons (from notes/learnings.md), each with evidence
Schema: exports/README.md.
"""

import csv
import json
import sqlite3
from collections import Counter
from pathlib import Path

from arena_kit.cost import total_cost
from arena_kit.docs import quote_terms

ROOT = Path(__file__).resolve().parents[1]
LOGS, OUT = ROOT / "logs" / "sessions", ROOT / "exports"
DB = sqlite3.connect(ROOT / "data" / "package" / "world.sqlite")
TERMS = [
    "unit_price",
    "payment_days",
    "contract_months",
    "volume_per_year",
    "effective_date",
    "lead_time_days",
    "incoterm",
    "index_clause",
    "tooling_eur",
    "ppm_commitment",
    "chargeback_eur_per_complaint",
]
PARTS = [
    "price",
    "uncovered_need",
    "fallback_risk",
    "payment_terms",
    "freight",
    "late_delivery",
    "quality",
    "tooling",
    "index_clause",
    "index_risk",
    "relationship",
]


def cases():
    out = {}
    for f in (ROOT / "logs" / "cases").glob("*.json"):
        out |= {c["case_id"]: c for c in json.loads(f.read_text())}
    return out


def profiles():
    path = ROOT / "analysis" / "out" / "profiles.csv"
    return {r["id"]: r for r in csv.DictReader(path.open())} if path.is_file() else {}


def should_cost(parts, supplier):
    total = 0.0
    for part in parts:
        rows = DB.execute("SELECT supplier_id, unit_cost FROM should_cost WHERE part_id = ?", (part,)).fetchall()
        if not rows:
            return None
        total += next((c for s, c in rows if s == supplier), rows[0][1])
    return round(total, 2)


def standard(messages):
    for m in messages:
        for a in m.get("attachments") or []:
            if a.get("name", "").startswith("quote") and a.get("text"):
                return quote_terms(a["text"]).get("standard", {})
    return {}


def cost(case, terms, std):
    try:
        return round(total_cost(case, terms, std), 2) if case and terms and terms.get("unit_price") else None
    except Exception:
        return None


def implied_price(case, terms, c_best, std):
    """The unit price at which the other terms of `terms` cost exactly C_best."""
    lo, hi = 0.0, 10 * (terms.get("unit_price") or 1)
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if total_cost(case, {**terms, "unit_price": mid}, std) < c_best else (lo, mid)
    return round(lo, 2)


def method(probe):
    if isinstance(probe, dict):
        return f"sandbox A/B: {probe.get('variant')}"
    if not probe:
        return "kit naive agent"
    return "autoprobe v1" if "sent" in probe[0] else "scripted probe (resumed by hand)"


def export():
    cs, prof = cases(), profiles()
    sessions, threads, messages, claims = [], [], [], []
    for path in sorted(LOGS.glob("*/*.json")):
        s = json.loads(path.read_text())
        r, case = s.get("result") or {}, cs.get(s["case_id"])
        if not case or not r.get("trace"):
            continue
        b, msgs, bo = case["buyer"], s.get("messages") or {}, s.get("backoffice") or []
        probe = s.get("probe")
        probe_rows = probe if isinstance(probe, list) else []
        stds = {sid: standard(msgs.get(sid, [])) for sid in case["suppliers"]}
        terms = r.get("terms") or {}
        sid_deal = r.get("supplier_id")
        sessions.append(
            {
                "set": s["set"],
                "case_id": s["case_id"],
                "session_id": s["session_id"],
                "title": case["title"],
                "type": case["type"],
                "category_goal": b["category_goal"],
                "suppliers": len(case["suppliers"]),
                "method": method(probe),
                "end_reason": s.get("end_reason"),
                "deal": bool(r.get("deal")),
                "deal_supplier": sid_deal,
                "score": r.get("score"),
                "c_open": r.get("c_open"),
                "c_deal": r.get("c_deal"),
                "c_alt": r.get("c_alt"),
                "c_best": r.get("c_best"),
                "gap_to_best_eur": round(r["c_deal"] - r["c_best"], 2) if r.get("deal") else None,
                "implied_price_at_deal_terms": implied_price(case, terms, r["c_best"], stds.get(sid_deal, {}))
                if r.get("deal")
                else None,
                "need_per_year": b["need_per_year"],
                "horizon_years": b["horizon_years"],
                "current_unit_price": b.get("current_unit_price"),
                "fallback_unit_price": b["fallback_unit_price"],
                **{f"deal_{k}": (json.dumps(terms.get(k)) if k == "index_clause" else terms.get(k)) for k in TERMS},
                **{f"cost_{k}": (r.get("cost_breakdown") or {}).get(k) for k in PARTS},
            }
        )
        for sid in case["suppliers"]:
            p, std = prof.get(sid, {}), stds[sid]
            steps = [t for t in r["trace"] if t["actor"] == sid or t["move"].get("supplier_id") == sid]
            mine = [t for t in steps if t["actor"] == sid]
            notes = [x for x in probe_rows if x.get("supplier_id") == sid and x.get("key") != "close"]
            atts = [a["name"] for m in msgs.get(sid, []) for a in m.get("attachments") or []]
            prices = [(t["move"].get("terms") or {}).get("unit_price") for t in mine]
            prices = [x for x in prices if x is not None]
            sc = should_cost(case["parts"], sid)
            statuses = [t["move"].get("status") for t in mine]
            questions = Counter(q for t in mine for q in t.get("reasons") or [] if q.strip().endswith("?"))
            calls = Counter(x["text"] for x in bo if x.get("supplier_id") == sid and x["text"].startswith("My call"))
            threads.append(
                {
                    "set": s["set"],
                    "case_id": s["case_id"],
                    "session_id": s["session_id"],
                    "supplier_id": sid,
                    "supplier_name": p.get("name")
                    or next((x["supplier"] for x in bo if x.get("supplier_id") == sid), ""),
                    "country": p.get("country"),
                    "owner_type": p.get("owner_type"),
                    "credit_index": p.get("credit_index"),
                    "scorecard_colour": p.get("colour"),
                    "data_signals": p.get("signals"),
                    "should_cost": sc,
                    "opening_price": prices[0] if prices else None,
                    "final_price": prices[-1] if prices else None,
                    "price_move_pct": round((prices[-1] / prices[0] - 1) * 100, 2) if len(prices) > 1 else 0.0,
                    "opening_vs_should_cost_pct": round((prices[0] / sc - 1) * 100, 1) if sc and prices else None,
                    "final_status": statuses[-1] if statuses else None,
                    "first_agreed_round": next((t["round"] for t in mine if t["move"].get("status") == "agreed"), None),
                    "buyer_messages": sum(t["actor"] == "buyer" for t in steps),
                    "won_deal": sid == sid_deal,
                    "standard_terms": json.dumps(std),
                    "documents": json.dumps(sorted(set(atts))),
                    "sent_cost_breakdown": any("cost" in a and "breakdown" in a for a in atts),
                    "probe_steps": json.dumps([x["key"] for x in notes]),
                    "questions": json.dumps(dict(questions.most_common(5)), ensure_ascii=False),
                    "backoffice_calls": json.dumps(dict(calls), ensure_ascii=False),
                }
            )
            n_buyer = 0
            for t in steps:
                m, ours = t["move"], t["actor"] == "buyer"
                note = notes[n_buyer] if ours and n_buyer < len(notes) else {}
                n_buyer += ours
                sheets = (
                    [x["terms"] for x in m.get("term_sheets") or []]
                    if ours
                    else ([m["terms"]] if m.get("terms") else [])
                )
                row = {
                    "set": s["set"],
                    "case_id": s["case_id"],
                    "session_id": s["session_id"],
                    "supplier_id": sid,
                    "round": t["round"],
                    "actor": "buyer" if ours else "supplier",
                    "probe_step": note.get("key"),
                    "probe_note": note.get("note"),
                    "action": m.get("type") if m.get("type") in ("accept", "walk_away") else None,
                    "status": m.get("status"),
                    "sheets": [{"terms": x, "c": cost(case, x, std)} for x in sheets],
                    "claims_made": (m.get("interpreted") or {}).get("claims") if ours else m.get("claims"),
                    "claim_results": m.get("claim_results"),
                    "missing_fields": m.get("missing_fields"),
                    "signals": m.get("signals"),
                    "reasons": t.get("reasons") or [],
                    "backoffice": [
                        x for x in bo if x.get("supplier_id") == sid and x["round"] == t["round"] and not ours
                    ],
                    "text": m.get("body") if ours else m.get("text"),
                }
                messages.append(row)
            # pair each argument we made with the check in the supplier's next reply
            for i, t in enumerate(steps):
                if t["actor"] != "buyer":
                    continue
                made = (t["move"].get("interpreted") or {}).get("claims") or []
                reply = next((x for x in steps[i + 1 :] if x["actor"] == sid), None)
                results = {c["index"]: c["result"] for c in ((reply or {}).get("move", {}).get("claim_results") or [])}
                for j, c in enumerate(made):
                    claims.append(
                        {
                            "set": s["set"],
                            "case_id": s["case_id"],
                            "session_id": s["session_id"],
                            "supplier_id": sid,
                            "round": t["round"],
                            "type": c.get("type"),
                            "refs": " ".join(c.get("refs") or []),
                            "asserted": json.dumps(c.get("asserted")),
                            "result": results.get(j),
                        }
                    )
    OUT.mkdir(exist_ok=True)
    write(OUT / "sessions", sessions)
    write(OUT / "threads", threads)
    write(OUT / "messages", messages, csv_too=False)
    write(OUT / "claims", claims, jsonl=False)
    print(f"{len(sessions)} sessions, {len(threads)} threads, {len(messages)} messages, {len(claims)} claims -> {OUT}")


def write(stem, rows, csv_too=True, jsonl=True):
    if jsonl:
        with stem.with_suffix(".jsonl").open("w") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    if csv_too and rows:
        with stem.with_suffix(".csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
            w.writeheader()
            w.writerows(rows)


if __name__ == "__main__":
    export()
