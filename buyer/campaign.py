"""`buyer campaign`: the team's practice budget, run by run from one command, keyboard only.

The queue comes from the arena, so every teammate sees the same state: first every hosted case
once, one of each case type before the second of any; then replays of the cases with the most room
left (lowest best score). It stops when the team has played `budget` practice sessions, and skips
a case someone is playing right now. Each run is the probe console; after it the session is saved
and the session page rebuilt.
"""

import json

from arena_kit.play import hosted

from .console import Console
from .harvest import save
from .view import build

SUMMARY = ("deal", "score", "c_open", "c_deal", "c_alt", "c_best")


def queue(cases, sessions, best, budget):
    """Case IDs still to play, in order, within the budget."""
    playable = sorted(hosted(list(cases)), key=lambda c: c["case_id"])
    played = {s["case_id"] for s in sessions}
    by_type = {}
    for c in playable:
        by_type.setdefault(c["type"], []).append(c["case_id"])
    first = []
    while any(by_type.values()):  # one of each type, then the next of each
        for ids in by_type.values():
            if ids:
                first.append(ids.pop(0))
    todo = [c for c in first if c not in played]
    replays = sorted((c for c in first if c in played), key=lambda c: best.get(c, 0.0))
    left = max(0, budget - len(sessions))
    return (todo + replays)[:left]


def ask(prompt):
    try:
        return input(prompt).strip().lower()
    except EOFError:
        return "q"


def run(client, package, budget, suggester=None):
    skipped = set()
    while True:
        sessions = client.sessions("practice")
        running = {s["case_id"] for s in sessions if s["status"] == "open"}
        cases = {c["case_id"]: c for c in client.cases("practice")}
        best = client.me().get("best", {})
        todo = [c for c in queue(cases.values(), sessions, best, budget) if c not in running | skipped]
        print(f"\n== practice: {len(sessions)} of {budget} used by the team; next: {', '.join(todo[:5]) or '-'}")
        if not todo:
            print("budget used or nothing left to play")
            return
        c = cases[todo[0]]
        replay = any(s["case_id"] == c["case_id"] for s in sessions)
        again = f", replay (best so far {best.get(c['case_id'], 0):.2f})" if replay else ""
        key = ask(
            f"Next: {c['case_id']} {c['title']} ({c['type']}, {len(c['suppliers'])} supplier(s)){again}. "
            "Enter = start, s = skip, q = quit: "
        )
        if key == "q":
            return
        if key == "s":
            skipped.add(c["case_id"])
            continue
        console = Console(client, c["case_id"], package, suggester=suggester)
        result = console.run()
        print(json.dumps({k: result.get(k) for k in SUMMARY}, indent=2))
        print(f"saved {save(client, console.table.session_id, probe=console.log)}")
        print(f"session page: {build(client)}  (uv run buyer view --offline opens it)")
