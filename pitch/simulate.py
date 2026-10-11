"""Export an offline test of the current buyer for the pipeline UI.

Run from the repo root: uv run python pitch/simulate.py
The real runner/policy/cost engine play arena-kit S02 in process. Model replies are
scripted fixtures, not live inference. No HTTP, key, quota or production memory.
"""

import copy
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from arena_kit import must_haves_ok, total_cost
from arena_kit.data import DataPackage
from arena_kit.sim import Sim, load_cases

from buyer import analyst, memory, rehearsal, research, runner
from buyer.policy import Negotiator

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "pitch/src/simulation.json"


def scripted(system, user):
    """Deliberately conservative fixtures; no claim to model quality."""
    if system == research.LEAD:
        answer = {
            "trades": [],
            "claim_order": ["should_cost", "index", "scorecard"],
            "tone": "businesslike",
            "notes": "Use the recorded evidence and keep the proposal clear.",
            "reason": "Scripted test strategy; all figures come from the policy.",
        }
    elif system == rehearsal.SUPPLIER:
        answer = {
            "arguments": ["Our production costs leave limited room to move."],
            "weak_points": [],
            "wants": ["a clear purchase commitment"],
        }
    elif system == rehearsal.BUYER:
        answer = {
            "rebuttals": [{"to": 1, "answer": "Let us review the complete package against the available evidence."}],
            "press": [],
        }
    elif system == analyst.SYSTEM:
        answer = {
            "mood": "neutral",
            "tactic": "steady",
            "argument": 0,
            "asks": [],
            "notes": "Acknowledge the counter and respond with a complete proposal.",
        }
    elif system == memory.DEBRIEF:
        answer = {"lesson": "This scripted run exercised the complete pipeline. Validate tactics on further cases."}
    elif "JSON only" in system:
        answer = {"findings": ["Use the supplied records to substantiate the proposal."], "leverage": "balanced"}
    else:
        return "Thank you for your proposal. Please consider the complete package below."
    return json.dumps(answer)


def generate(package=None):
    case = copy.deepcopy(load_cases()["case:S02"])
    case["round_limit"] = 3  # Short presentation case; production policy and kit are unchanged.
    sim = Sim({case["case_id"]: case}, package.facts if package else {}, no_clock=True)
    events, state, calls = [], {}, {}

    def model(system, user):
        role = next(
            (
                name
                for name, prompt in (
                    ("lead", research.LEAD),
                    ("supplier", rehearsal.SUPPLIER),
                    ("buyer", rehearsal.BUYER),
                    ("analyst", analyst.SYSTEM),
                    ("debrief", memory.DEBRIEF),
                )
                if system == prompt
            ),
            "specialist" if "JSON only" in system else "writer",
        )
        calls[role] = calls.get(role, 0) + 1
        return scripted(system, user)

    def emit(stage, title, summary, supplier=None, detail=None):
        costs = [s["cost"] for s in state.values() if s.get("cost") is not None]
        events.append(
            {
                "stage": stage,
                "title": title,
                "summary": summary,
                "supplier": supplier,
                "detail": detail or {},
                "suppliers": copy.deepcopy(state),
                "best": min(costs) if costs else None,
            }
        )

    def standing(sid, reply):
        terms = (reply.get("term_sheets") or [{}])[0].get("terms", {})
        std = sim.sessions[table.session_id]["threads"][sid]["standard"]
        valid = bool(terms) and must_haves_ok(case, terms, std)
        state[sid] = {
            **state.get(sid, {}),
            "price": terms.get("unit_price"),
            "status": reply.get("status", "open"),
            "cost": round(total_cost(case, terms, std), 2) if valid else None,
            "terms": terms,
            "valid": valid,
        }

    class Table:
        def __init__(self):
            self.case, self.session_id = case, None

        def open(self, case_id):
            briefs = research.CACHE.get(case_id, {})
            emit(
                "research",
                "Supplier briefs prepared",
                "Four specialist roles and a lead review each supplier.",
                detail={"briefs": briefs, "model_calls": dict(calls)},
            )
            emit(
                "rehearsal",
                "Arguments rehearsed",
                "A supplier role raises objections; a buyer role prepares responses.",
                detail={sid: brief.get("playbook", {}) for sid, brief in briefs.items()},
            )
            opened = sim.open("ui-test", case_id)
            self.session_id = opened["session_id"]
            for sid, messages in opened["threads"].items():
                standing(sid, messages[-1])
            emit(
                "analyst",
                "Opening quotes received",
                "The runner opens supplier threads and starts the reply clocks.",
                detail={"quotes": opened["opening"]},
            )
            return opened["case"], opened["threads"]

        def send(self, supplier_id, message):
            sheets = message.get("term_sheets") or []
            if sheets:
                state[supplier_id]["ours"] = sheets[0]["terms"]["unit_price"]
            emit(
                "writer",
                "Proposal sent",
                "Code supplies the figures and claims; the writer supplies the words.",
                supplier_id,
                {"message": message},
            )
            reply = sim.message("ui-test", self.session_id, supplier_id, message)
            standing(supplier_id, reply)
            emit(
                "analyst",
                "Supplier replied",
                "The standing quote updates before the next decision.",
                supplier_id,
                {"reply": reply},
            )
            return reply

        def close(self, supplier_id, message):
            reply = sim.message("ui-test", self.session_id, supplier_id, message)
            result = reply.get("result", reply)
            if result.get("deal"):
                standing(supplier_id, reply)
                state[supplier_id]["status"] = "accepted"
            emit(
                "close",
                "Deal accepted" if result.get("deal") else "Walked away",
                "The close gate checks the standing sheet, must-haves and total cost.",
                supplier_id,
                {"result": result},
            )
            return result

        def attachment(self, attachment_id):
            return sim.attachment("ui-test", self.session_id, attachment_id)[0]

    table = Table()
    note = Negotiator.note

    def capture(neg, sid, what, **kw):
        note(neg, sid, what, **kw)
        if what == "send":
            emit(
                "negotiator",
                "Offer priced and checked",
                "The policy sets price, complete terms and supporting claims.",
                sid,
                kw,
            )
        elif what == "analyst":
            emit(
                "analyst",
                "Reply interpreted",
                "The analyst selects a bounded tactic; the policy controls its effect.",
                sid,
                kw,
            )

    with tempfile.TemporaryDirectory(prefix="buyer-ui-") as folder:
        lesson_file = Path(folder) / "lessons.jsonl"
        with (
            patch.object(runner, "RUNS", Path(folder)),
            patch.object(memory, "LESSONS", lesson_file),
            patch.object(research, "CACHE", {}),
            patch.object(Negotiator, "note", capture),
        ):
            result = runner.play_case(table, case["case_id"], pkg=package, complete=model)
            lesson = json.loads(lesson_file.read_text().splitlines()[-1]) if lesson_file.exists() else {}
        emit(
            "debrief",
            "Run complete · lesson saved",
            "Observed outcomes are saved for research on similar cases.",
            detail={"lesson": lesson},
        )

    suppliers = []
    for sid in case["suppliers"]:
        rows = package.query("SELECT name FROM suppliers WHERE id = ?", (sid,), 1) if package else []
        suppliers.append({"id": sid, "name": rows[0]["name"] if rows else sid})
    fingerprint = hashlib.sha256(b"".join(p.read_bytes() for p in sorted((ROOT / "buyer").glob("*.py")))).hexdigest()[
        :12
    ]
    return {
        "id": f"local-S02-short-{fingerprint}",
        "source": "arena-kit simulator",
        "model": "scripted fixtures",
        "commit": subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip(),
        "fingerprint": fingerprint,
        "sample_size": 1,
        "scenario": "S02 shortened to three rounds per supplier",
        "case": case,
        "suppliers": suppliers,
        "events": events,
        "result": result,
        "calls": calls,
        "has_package": package is not None,
    }


if __name__ == "__main__":
    data = ROOT / "data/package"
    output = generate(DataPackage(data) if data.is_dir() else None)
    OUTPUT.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n")
    print(f"{OUTPUT.relative_to(ROOT)}: {len(output['events'])} events; deal={output['result']['deal']}")
