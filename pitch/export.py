r"""One recorded session as `pitch/src/replay.json` for the pitch monitor: our decisions (`logs/runs`),
the arena's trace (`logs/sessions`), the verbose run log (the team's briefs and timings), the case
file (`logs/cases`) and the debrief's lesson (a lessons file, `buyer/lessons.jsonl` by default).
Local files only: no arena call, no key. The demo bidding is replayed with the agent's own
`rehearsal.bid` and `policy.step`, so run it on the engine that played the session: 237a761b
was played by a7ef22e (`joao/improvements-louis`), e.g. from `git worktree add ../replay a7ef22e`.

    uv run python pitch/export.py logs/runs/P05_237a761baedb7462.json --log logs/pitch-P05.log \
        --lessons logs/pitch-P05-lesson.jsonl
"""

import argparse
import datetime
import json
import re
from pathlib import Path

from arena_kit import must_haves_ok, total_cost
from arena_kit.data import DataPackage

from buyer import policy, rehearsal
from buyer.research import PLAYBOOKS

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent / "src" / "replay.json"
CLOCK = re.compile(r"^(\d\d):(\d\d):(\d\d) ")
POST = re.compile(r"POST \S+/threads/(sup:[\w-]+)/messages \"HTTP/1.1 200")


def seconds(line):
    """Seconds of the day of a log line, or None."""
    m = CLOCK.match(line)
    return int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3]) if m else None


def of_day(epoch):
    t = datetime.datetime.fromtimestamp(epoch)
    return t.hour * 3600 + t.minute * 60 + t.second + t.microsecond / 1e6


def short(name):
    """'Zerspanung Dralveck GmbH' -> 'Dralveck': the word before the legal form."""
    words = name.split()
    return words[-2] if len(words) > 2 else words[0]


def case_file(case_id):
    for path in sorted((ROOT / "logs" / "cases").glob("*.json")):
        for case in json.loads(path.read_text()):
            if case["case_id"] == case_id:
                return case
    raise SystemExit(f"{case_id}: no case file in logs/cases")


def demo(model, anchor, fraction, budget):
    """One demo negotiation as `rehearsal.bid` plays it, with both price paths."""
    ours, theirs = [anchor], [1.0]

    def recording(last, their, *rest):
        theirs.append(their)
        ours.append(policy.step(last, their, *rest))
        return ours[-1]

    price, end = rehearsal.bid(recording, model, anchor, fraction, budget)
    return {"anchor": anchor, "fraction": fraction, "ours": ours, "theirs": theirs, "price": price, "end": end}


def race(note, budget):
    """Every demo negotiation of the grid with both price paths, in shares of the quote."""
    ratio, proposal = note["default"], tuple(note["proposal"])
    low, high = policy.ANCHOR_MIN, min(1.0, ratio + 0.02)
    grid = [(d, f) for d in rehearsal.SHIFTS for f in rehearsal.FRACTIONS]
    if proposal not in grid:
        grid.append(proposal)
    runs = [demo(note["playbook"], round(min(high, max(low, ratio + d)), 4), f, budget) for d, f in grid]
    chosen = rehearsal.tune(policy.step, note["playbook"], ratio, budget, proposal, low, high)
    assert (chosen[0], chosen[1]) == (note["ratio"], note["fraction"]), "replayed choice differs from the run"
    return {"default": ratio, "anchor": chosen[0], "fraction": chosen[1], "runs": runs}


def why(sends, note):
    """How the price engine set this price: open at the anchor, hold it after a deep first drop
    (`policy.DEEP`), else move a share of the gap. `conceded`: its drop since our last e-mail."""
    k = next(i for i, n in enumerate(sends) if n is note)
    if k == 0:
        return {"rule": "anchor", "conceded": None}
    before = sends[k - 1]["theirs"]
    conceded = round((before - note["theirs"]) / before, 4)
    return {"rule": "hold" if k == 1 and conceded >= policy.DEEP else "step", "conceded": conceded}


def lesson(session_result, path):
    """The debrief row this session wrote: same score and price path."""
    for line in reversed(Path(path).read_text().splitlines()):
        row = json.loads(line)
        if row.get("score") == round(session_result["score"], 3) and row.get("deal") == session_result["deal"]:
            return row
    raise SystemExit("no debrief row for this session in the lessons file")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run", help="logs/runs/<case>_<session>.json")
    ap.add_argument("--log", required=True, help="the verbose log of that run")
    ap.add_argument("--lessons", default=str(ROOT / "buyer" / "lessons.jsonl"))
    ap.add_argument("--data", default=str(ROOT / "data" / "package"))
    args = ap.parse_args()

    run = json.loads(Path(args.run).read_text())
    session_id, case_id = run["session"], run["case"]
    session = json.loads(next((ROOT / "logs" / "sessions").glob(f"*/*_{session_id}.json")).read_text())
    case = case_file(case_id)
    pkg = DataPackage(args.data)
    lines = Path(args.log).read_text().splitlines()
    notes = run["notes"]
    result = session["result"]

    # the clock: 0 is the start of the research, before the session opened
    done_line = next(line for line in lines if " research in " in line)
    brief_s = float(re.search(r"research in ([\d.]+)s", done_line)[1])
    briefs = json.loads(done_line.split("s: ", 1)[1])
    t0 = seconds(done_line) - brief_s

    def rel(epoch):
        return round(of_day(epoch) - t0, 1)

    names = {}
    for sid in case["suppliers"]:
        rows = pkg.query("SELECT name, country FROM suppliers WHERE id = ?", (sid,), 1)
        names[sid] = rows[0] if rows else {"name": sid, "country": None}

    by_note = {}
    for n in notes:
        by_note.setdefault((n["what"], n["supplier"]), []).append(n)

    suppliers = []
    for sid in case["suppliers"]:
        setup = by_note[("setup", sid)][0]
        opening = session["opening"][sid]
        suppliers.append(
            {
                "id": sid,
                "name": names[sid]["name"],
                "short": short(names[sid]["name"]),
                "country": names[sid]["country"],
                "owner": setup["profile"].get("owner_type"),
                "signals": setup["profile"].get("signals", []),
                "quote": opening["terms"],
                "quote_text": opening.get("text"),
                "std": setup["std"],
                "anchor": setup["anchor"],
                "quote_at_terms": setup["quote_at_terms"],
                "budget": setup["budget"],
                "claims": setup["claims"],
            }
        )

    research = {}
    for sid, brief in briefs.items():
        note = by_note[("research", sid)][0]
        setup = by_note[("setup", sid)][0]
        research[sid] = {
            "findings": brief.get("findings", {}),
            "strategy": {k: brief.get(k) for k in ("shift", "fraction", "claim_order", "tone", "notes", "reason")},
            "playbook": brief.get("model"),
            "rehearsal": race(note, setup["budget"]) if note["demo"] else None,
            "opening": note["ratio"],
        }

    # the writer: one log line per message we composed, in order
    writer = [
        {"t": round(seconds(line) - t0, 1), "model": "writer paragraph in" in line}
        for line in lines
        if "writer paragraph in" in line or "writer skipped" in line
    ]
    replies = {}
    for line in lines:
        m = POST.search(line)
        if m:
            replies.setdefault(m[1], []).append(round(seconds(line) - t0, 1))

    # the conversation: the arena's trace, paired with our send notes and the reply times
    events = [{"t": 0.0, "kind": "research", "until": brief_s}]
    opened = rel(notes[0]["t"])
    events.append({"t": opened, "kind": "open", "quotes": {s["id"]: s["quote"] for s in suppliers}})
    for n in notes:
        if n["what"] == "analyst":
            events.append(
                {
                    "t": rel(n["t"]),
                    "kind": "analyst",
                    "supplier": n["supplier"],
                    "seconds": n["seconds"],
                    "mood": n["mood"],
                    "asks": n["asks"],
                    "notes": n["notes"],
                }
            )
    sends = iter(n for n in notes if n["what"] == "send")
    writes = iter(writer)
    seen = {}
    pending = {}
    for step in result["trace"]:
        move = step.get("move") or {}
        if step["actor"] == "buyer":
            sid = move.get("supplier_id")
            if move.get("type") == "accept":
                continue
            sheets = [s["terms"] for s in move.get("term_sheets") or []]
            if not sheets:  # a question to a finished bidder while the others negotiate
                events.append({"t": None, "kind": "keepalive", "supplier": sid, "round": step["round"]})
                pending[sid] = events[-1]
                continue
            note, write = next(sends), next(writes)
            events.append(
                {
                    "t": rel(note["t"]),
                    "kind": "send",
                    "supplier": sid,
                    "round": step["round"],
                    "price": sheets[0]["unit_price"],
                    "terms": sheets[0],
                    "claims": note["claims"],
                    "refs": move.get("refs") or [],
                    "body": move.get("body"),
                    "subject": move.get("subject"),
                    "model_paragraph": write["model"],
                    "theirs": note["theirs"],
                    **why(by_note[("send", sid)], note),
                }
            )
            pending[sid] = events[-1]
        else:
            sid = step["actor"]
            if step["round"] == 0:
                continue
            k = seen.get(sid, 0)
            seen[sid] = k + 1
            t = replies[sid][k] if k < len(replies.get(sid, [])) else None
            sent = pending.pop(sid, None)
            if sent and sent["t"] is None:
                sent["t"] = t
            elif sent and t is not None:  # the log has whole seconds, the notes tenths
                t = max(t, round(sent["t"] + 0.2, 1))
            events.append(
                {
                    "t": t,
                    "kind": "reply",
                    "supplier": sid,
                    "round": step["round"],
                    "status": move.get("status"),
                    "price": (move.get("terms") or {}).get("unit_price"),
                    "terms": move.get("terms"),
                    "checks": [c["result"] for c in move.get("claim_results") or []],
                    "text": move.get("text"),
                    "reasons": step.get("reasons") or [],
                }
            )

    # the best valid standing sheet after each event, at total cost
    std = {s["id"]: s["std"] for s in suppliers}

    def cost(sid, terms):
        """C of a sheet, unstated fields at its standard terms; None when it breaks a must-have."""
        if not must_haves_ok(case, terms, std[sid]):
            return None
        return round(total_cost(case, terms, std[sid]), 2)

    standing = {s["id"]: cost(s["id"], s["quote"]) for s in suppliers}
    for e in sorted((e for e in events if e["t"] is not None), key=lambda e: e["t"]):
        if e["kind"] == "reply" and e["terms"]:
            standing[e["supplier"]] = cost(e["supplier"], e["terms"])
        if e["kind"] in ("open", "reply"):
            e["standing"] = dict(standing)

    accept = by_note[("accept", result["supplier_id"])][0]
    closing = {
        "t": rel(accept["t"]),
        "supplier": result["supplier_id"],
        "terms": result["terms"],
        "c_open": result["c_open"],
        "c_deal": result["c_deal"],
        "c_best": result["c_best"],
        "score": result["score"],
        "breakdown": result["cost_breakdown"],
        "standing": dict(standing),
    }
    assert abs(standing[result["supplier_id"]] - result["c_deal"]) < 1, "our C differs from the arena's"
    debrief = lesson(result, args.lessons)
    after = [seconds(line) for line in lines if "chat/completions" in line and seconds(line) - t0 > closing["t"]]
    events.append(
        {
            "t": closing["t"],
            "kind": "accept",
            "supplier": result["supplier_id"],
            "price": closing["terms"]["unit_price"],
        }
    )
    events.append({"t": round((after[-1] if after else seconds(lines[-1])) - t0, 1), "kind": "debrief"})

    calls = {
        "research": sum(len(r["findings"]) for r in research.values()) + len(research),
        "roleplay": PLAYBOOKS * len(research),
        "analyst": sum(1 for e in events if e["kind"] == "analyst"),
        "writer": sum(1 for w in writer if w["model"]),
        "debrief": 1,
    }
    out = {
        "case": {
            "id": case_id.split(":")[-1],
            "title": case["title"],
            "type": case["type"],
            "goal": case["buyer"]["category_goal"],
            "need_per_year": case["buyer"]["need_per_year"],
            "horizon_years": case["buyer"]["horizon_years"],
            "current_price": case["buyer"]["current_unit_price"],
            "must_haves": case["buyer"]["must_haves"],
            "negotiable": case["negotiable"],
        },
        "session": {
            "id": session_id,
            "set": session["set"],
            "recorded": datetime.datetime.fromtimestamp(notes[0]["t"]).isoformat(timespec="minutes"),
            "end": max(e["t"] for e in events if e["t"] is not None),
        },
        "calls": calls,
        "suppliers": suppliers,
        "research": research,
        "events": sorted(events, key=lambda e: (e["t"] is None, e["t"] or 0)),
        "close": closing,
        "lesson": debrief,
    }
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(f"{OUT.relative_to(ROOT)}: {len(events)} events, calls {calls}")


if __name__ == "__main__":
    main()
