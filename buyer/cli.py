"""`buyer` command line: play one case or a whole set with our agent, probe a case with a person
picking the moves, and pull finished sessions (result, trace with the supplier's reasons, back
office, attachments) into logs/ for the learning loop."""

import argparse
import functools
import json
import logging
import os
import statistics

from arena_kit import ArenaClient, ArenaError, RemoteTable, play, play_all
from arena_kit.agents import llm_from_env
from arena_kit.cli import load_env, summary
from arena_kit.data import DataPackage
from arena_kit.play import hosted, play_waves

from .agent import AGENTS, agent_factory
from .console import AUTO_AFTER_S, Console
from .harvest import pull, save
from .suggest import Suggester


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
    pr = sub.add_parser("probe", help="play one case yourself: pick each move from options built in code")
    pr.add_argument("case_id")
    pr.add_argument("--data", **data)
    pr.add_argument("--auto", type=float, default=AUTO_AFTER_S, help="seconds until the default move goes out")
    pr.add_argument("--no-ai", action="store_true", help="code options only, no model suggestions")
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
    if args.cmd == "probe":
        return probe(client, args)
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


def probe(client, args):
    """A practice case costs one session of the team's quota: say so and ask first."""
    if not any(c["case_id"] == args.case_id for c in client.cases("sandbox")):
        left = client.me()["practice"]["left"]
        if input(f"{args.case_id} costs 1 practice session ({left} left today). Go? [y/N] ").strip().lower() != "y":
            return
    package = DataPackage(args.data) if args.data else None
    suggester = None
    if not args.no_ai:
        try:
            suggester = Suggester(llm_from_env(), package)
        except KeyError as e:
            print(f"AI suggestions off: {e} is not set")
    console = Console(client, args.case_id, package, auto_after=args.auto, suggester=suggester)
    result = console.run()
    keep = ("deal", "score", "c_open", "c_deal", "c_alt", "c_best", "terms", "cost_breakdown")
    print(json.dumps({k: result.get(k) for k in keep}, indent=2))
    path = save(client, console.table.session_id, probe=console.log)
    print(f"saved {path}")


if __name__ == "__main__":
    main()
