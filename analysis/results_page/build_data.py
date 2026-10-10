"""Compact data for the results page, from exports/."""

import csv
import json
import sys
from pathlib import Path

EX = Path(sys.argv[1])
OUT = Path(sys.argv[2])
sessions = [r for r in csv.DictReader(open(EX / "sessions.csv")) if r["set"] == "practice"]
threads = [r for r in csv.DictReader(open(EX / "threads.csv")) if r["set"] == "practice"]
msgs = [json.loads(line) for line in open(EX / "messages.jsonl")]
msgs = [m for m in msgs if m["set"] == "practice"]
claims = [r for r in csv.DictReader(open(EX / "claims.csv")) if r["set"] == "practice"]
findings = json.load(open(EX / "findings.json"))["findings"]


def f(x):
    return float(x) if x not in ("", None) else None


runs = []
for s in sessions:
    runs.append(
        {
            "case": s["case_id"].split(":")[1],
            "sid": s["session_id"],
            "title": s["title"],
            "type": s["type"],
            "goal": s["category_goal"],
            "method": s["method"],
            "deal": s["deal"] == "True",
            "supplier": s["deal_supplier"],
            "score": f(s["score"]),
            "c_open": f(s["c_open"]),
            "c_deal": f(s["c_deal"]),
            "c_best": f(s["c_best"]),
            "c_alt": f(s["c_alt"]),
            "price": f(s["deal_unit_price"]),
            "implied": f(s["implied_price_at_deal_terms"]),
            "pay": s["deal_payment_days"],
            "months": s["deal_contract_months"],
            "uncovered": f(s["cost_uncovered_need"]),
            "suppliers": int(s["suppliers"]),
        }
    )
sups = {}
for t in threads:
    key = t["supplier_id"]
    path = [m for m in msgs if m["session_id"] == t["session_id"] and m["supplier_id"] == key]
    steps = []
    for m in path:
        if m["action"]:
            steps.append({"r": m["round"], "a": "us", "act": m["action"]})
            continue
        sh = m["sheets"]
        steps.append(
            {
                "r": m["round"],
                "a": "us" if m["actor"] == "buyer" else "them",
                "step": m["probe_step"],
                "note": m["probe_note"],
                "status": m["status"],
                "sheets": [{k: v for k, v in s["terms"].items() if v is not None} for s in sh],
                "claims": [c["result"] for c in (m["claim_results"] or [])],
                "reasons": [x for x in m["reasons"] if "…" not in x or len(x) < 140][:3]
                if m["actor"] == "supplier"
                else [],
            }
        )
    run = {
        "sid": t["session_id"],
        "case": t["case_id"].split(":")[1],
        "won": t["won_deal"] == "True",
        "opening": f(t["opening_price"]),
        "final": f(t["final_price"]),
        "status": t["final_status"],
        "agreed_round": t["first_agreed_round"] or None,
        "docs": json.loads(t["documents"]),
        "questions": json.loads(t["questions"]),
        "steps": steps,
    }
    s = sups.setdefault(
        key,
        {
            "id": key,
            "name": t["supplier_name"],
            "country": t["country"],
            "owner": t["owner_type"],
            "credit": t["credit_index"],
            "colour": t["scorecard_colour"],
            "signals": json.loads(t["data_signals"].replace("'", '"')) if t["data_signals"] else [],
            "should_cost": f(t["should_cost"]),
            "runs": [],
        },
    )
    s["runs"].append(run)
# payment-day pricing: same package, payment days moved, from the supplier's own counters
pay = []
for s in sups.values():
    for run in s["runs"]:
        them = [x for x in run["steps"] if x["a"] == "them" and x.get("sheets")]
        for a, b in zip(them, them[1:], strict=False):
            ta, tb = a["sheets"][0], b["sheets"][0]
            if "payment_days" not in ta or "payment_days" not in tb or ta["payment_days"] == tb["payment_days"]:
                continue
            same = all(ta.get(k) == tb.get(k) for k in set(ta) | set(tb) if k not in ("unit_price", "payment_days"))
            if not same or tb["payment_days"] <= ta["payment_days"]:
                continue
            dp = tb["unit_price"] / ta["unit_price"] - 1
            dd = tb["payment_days"] - ta["payment_days"]
            pay.append(
                {
                    "supplier": s["name"],
                    "id": s["id"],
                    "case": run["case"],
                    "from": ta["payment_days"],
                    "to": tb["payment_days"],
                    "p_from": ta["unit_price"],
                    "p_to": tb["unit_price"],
                    "pct": round(dp * 100, 2),
                    "rate": round(dp * 360 / dd * 100, 1),
                    "signals": s["signals"],
                }
            )
uniq = {}
for p in pay:
    uniq.setdefault((p["id"], p["from"], p["to"], p["p_from"]), p)
data = {
    "runs": runs,
    "suppliers": list(sups.values()),
    "payment": sorted(uniq.values(), key=lambda p: p["rate"]),
    "findings": findings,
    "claims": {
        "total": len(claims),
        "by_result": {
            k: sum(c["result"] == k for c in claims) for k in ("verified", "duplicate", "contradicted", "irrelevant")
        },
    },
    "sandbox_sessions": sum(1 for r in csv.DictReader(open(EX / "sessions.csv")) if r["set"] == "sandbox"),
}
OUT.write_text(json.dumps(data, ensure_ascii=False))
print(len(runs), "runs", len(sups), "suppliers", len(data["payment"]), "payment points", OUT.stat().st_size, "bytes")
for p in data["payment"]:
    print(p["supplier"], p["case"], p["from"], "->", p["to"], p["pct"], "% ->", p["rate"], "%/yr")
