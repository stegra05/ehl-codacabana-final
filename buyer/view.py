"""One page to read every saved session: `buyer view` pulls the team's sessions and opens it.

Per session: the score against C_open and C_best, the cost breakdown, and per thread every e-mail
in order with its term sheets and their C, claim results, the supplier's reasons, its back office
for that round, our probe note, and links to the attachments on disk.
"""

import json
import webbrowser
from pathlib import Path

from arena_kit.cost import total_cost
from arena_kit.docs import quote_terms

from .harvest import LOGS

PAGE = LOGS.parent / "view.html"
TEMPLATE = Path(__file__).with_name("view.html")


def _standard(messages):
    """The supplier's standard terms from the first quote PDF in the thread."""
    for m in messages:
        for att in m.get("attachments") or []:
            if att.get("name", "").startswith("quote") and att.get("text"):
                return quote_terms(att["text"]).get("standard", {})
    return {}


def _cost(case, terms, std):
    try:
        return total_cost(case, terms, std) if case and terms.get("unit_price") is not None else None
    except Exception:
        return None


def _session(path, cases):
    s = json.loads(path.read_text())
    r = s.get("result") or {}
    case = cases.get(s["case_id"])
    messages = s.get("messages") or {}
    backoffice = s.get("backoffice") or []
    probe = s.get("probe")
    probe_log = probe if isinstance(probe, list) else []
    threads = {}
    for step in r.get("trace") or []:
        move = step["move"]
        sid = move.get("supplier_id") if step["actor"] == "buyer" else step["actor"]
        threads.setdefault(sid, []).append(step)
    out = []
    for sid, steps in threads.items():
        std = _standard(messages.get(sid, []))
        supplier_msgs = [m for m in messages.get(sid, []) if m.get("from") != "buyer"]
        notes = [p for p in probe_log if p["supplier_id"] == sid]
        events, n_sup, n_buy = [], 0, 0
        for step in steps:
            move, mine = step["move"], step["actor"] == "buyer"
            sheets = [t["terms"] for t in move.get("term_sheets") or []] if mine else [move.get("terms") or {}]
            msg = None if mine else (supplier_msgs[n_sup] if n_sup < len(supplier_msgs) else None)
            events.append(
                {
                    "round": step["round"],
                    "mine": mine,
                    "from": "buyer" if mine else (msg or {}).get("from", sid),
                    "status": move.get("status"),
                    "body": move.get("body") if mine else move.get("text"),
                    "sheets": [{"terms": t, "c": _cost(case, t, std)} for t in sheets if t],
                    "claims": move.get("claim_results") or [],
                    "reasons": step.get("reasons") or [],
                    "signals": move.get("signals"),
                    "missing": move.get("missing_fields") or [],
                    "action": move.get("type") if mine and move.get("type") in ("accept", "walk_away") else None,
                    "attachments": [a["name"] for a in (msg or {}).get("attachments") or []],
                    "backoffice": [
                        b
                        for b in backoffice
                        if b.get("supplier_id") == sid and b["round"] == step["round"] and not mine
                    ],
                    "probe": notes[n_buy] if mine and n_buy < len(notes) else None,
                }
            )
            n_sup += not mine
            n_buy += mine
        out.append({"supplier_id": sid, "standard": std, "events": events})
    return {
        "file": path.stem,
        "dir": str((path.parent / path.stem).resolve()),
        "set": s.get("set"),
        "case_id": s["case_id"],
        "title": (case or {}).get("title", ""),
        "type": (case or {}).get("type", ""),
        "goal": ((case or {}).get("buyer") or {}).get("category_goal", ""),
        "end": s.get("end_reason"),
        "variant": probe.get("variant") if isinstance(probe, dict) else ("probe" if probe_log else ""),
        "result": {
            k: r.get(k)
            for k in ("deal", "score", "c_open", "c_deal", "c_alt", "c_best", "supplier_id", "terms", "cost_breakdown")
        },
        "threads": out,
    }


def build(client=None, root=LOGS):
    """Write the page from every saved session; case files come from the arena if a client is given."""
    cases = {}
    for set_ in ("practice", "sandbox"):
        try:
            cases |= {c["case_id"]: c for c in client.cases(set_)} if client else {}
        except Exception:
            pass
        cached = LOGS.parent / "cases" / f"{set_}.json"
        if cached.is_file():
            cases = {c["case_id"]: c for c in json.loads(cached.read_text())} | cases
    sessions = [_session(p, cases) for p in sorted(root.glob("*/*.json"))]
    sessions.sort(key=lambda s: s["file"].split("_")[0])
    PAGE.write_text(
        TEMPLATE.read_text().replace("__DATA__", json.dumps(sessions, ensure_ascii=False).replace("</", "<\\/"))
    )
    return PAGE


def open_page(path):
    webbrowser.open(path.resolve().as_uri())
