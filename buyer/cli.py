"""`buyer` command line: play one case or a whole set with our agent, and pull finished sessions
(result, trace with the supplier's reasons, back office) into logs/ for the learning loop."""

import argparse
import functools
import json
import logging
import os
import statistics
from pathlib import Path

from arena_kit import ArenaClient, ArenaError, RemoteTable, play, play_all
from arena_kit.cli import load_env, summary
from arena_kit.play import hosted, play_waves

from .agent import AGENTS, agent_factory

LOGS = Path("logs/sessions")


def pull(client, set_):
    """Save every ended session of a set that has its trace to logs/sessions/<set>/, once."""
    out = LOGS / set_
    out.mkdir(parents=True, exist_ok=True)
    saved = 0
    for s in client.sessions(set_):
        path = out / f"{s['case_id'].split(':')[-1]}_{s['session_id']}.json"
        if s["status"] != "ended" or path.exists():
            continue
        state = client.session(s["session_id"])
        if not (state.get("result") or {}).get("trace"):  # final: the trace comes after the final
            continue
        try:
            state["backoffice"] = client.backoffice(s["session_id"])
        except ArenaError:
            state["backoffice"] = None
        path.write_text(json.dumps(state, indent=2, ensure_ascii=False))
        saved += 1
    print(f"{saved} new sessions in {out}")


def main(argv=None):
    load_env()
    ap = argparse.ArgumentParser(prog="buyer")
    ap.add_argument("-v", "--verbose", action="store_true")
    verbose = argparse.ArgumentParser(add_help=False)  # -v also after the command
    verbose.add_argument("-v", "--verbose", action="store_true", default=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser = functools.partial(sub.add_parser, parents=[verbose])
    data = {"default": os.environ.get("ARENA_DATA"), "help": "data package folder"}
    p = sub.add_parser("play", help="play one case")
    p.add_argument("case_id")
    p.add_argument("--agent", default="buyer", choices=AGENTS)
    p.add_argument("--data", **data)
    r = sub.add_parser("run", help="play every playable case of a set in parallel; final: wave by wave")
    r.add_argument("--set", default="practice", choices=["practice", "sandbox", "final"])
    r.add_argument("--agent", default="buyer", choices=AGENTS)
    r.add_argument("--data", **data)
    r.add_argument("--parallel", type=int, default=8, help="cases at once (at most 10)")
    r.add_argument("--waves", type=int, default=5, help="final: stop after this many waves have closed")
    s = sub.add_parser("pull", help="save finished sessions with trace and back office to logs/sessions/")
    s.add_argument("--set", default="practice", choices=["practice", "sandbox", "final"])
    args = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(message)s",
        datefmt="%H:%M:%S",
    )
    client = ArenaClient()

    if args.cmd == "pull":
        return pull(client, args.set)
    new_agent = agent_factory(args.agent, args.data)
    if args.cmd == "play":
        table = RemoteTable(client)
        try:
            result = play(table, args.case_id, new_agent())
        except ArenaError as e:  # e.g. not hosted, the quota, a paused key: the arena says why
            raise SystemExit(str(e)) from None
        print(json.dumps(summary(result), indent=2))
        state = client.session(table.session_id)
        print(f"replay: {os.environ['ARENA_URL'].rstrip('/')}{state.get('replay_url')}")
        pull(client, state["set"])
    elif args.set == "final":  # no human in the loop: waits for each wave, plays it within its cap
        out = play_waves(client, new_agent, args.waves, min(args.parallel, 10))
        for case_id, result in out.items():
            print(case_id, result if isinstance(result, Exception) else summary(result))
    else:
        ids = [c["case_id"] for c in hosted(client.cases(args.set))]
        out = play_all(lambda: RemoteTable(client), ids, new_agent, min(args.parallel, 10))
        for case_id, result in out.items():
            print(case_id, result if isinstance(result, Exception) else summary(result))
        scores = [r["score"] for r in out.values() if isinstance(r, dict) and r.get("score") is not None]
        if scores:
            print(f"mean score: {100 * statistics.mean(scores):.1f} over {len(scores)} cases")
        pull(client, args.set)
    if client.practice_remaining is not None:
        print(f"practice sessions left today: {client.practice_remaining}")


if __name__ == "__main__":
    main()
