"""`buyer` command line: play one case or a whole set with our agent, probe practice cases
automatically, pull finished sessions (result, trace with the supplier's reasons, back office,
attachments) into logs/ and read them on one page."""

import argparse
import functools
import json
import logging
import os
import statistics
from concurrent.futures import ThreadPoolExecutor

from arena_kit import ArenaClient, ArenaError, RemoteTable, play, play_all
from arena_kit.cli import load_env, summary
from arena_kit.data import DataPackage
from arena_kit.play import hosted, play_waves

from .agent import AGENTS, agent_factory
from .autoprobe import AutoProbe
from .autoprobe import summary as probe_summary
from .harvest import pull, save
from .view import build, open_page


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
    ap_ = sub.add_parser("autoprobe", help="probe cases automatically, in parallel, and save every session")
    ap_.add_argument("case_ids", nargs="+")
    ap_.add_argument("--data", **data)
    ap_.add_argument("--parallel", type=int, default=10)
    v = sub.add_parser("view", help="pull the team's sessions and open them in the browser")
    v.add_argument("--offline", action="store_true", help="only what is saved already")
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
    if args.cmd == "view":
        if not args.offline:
            for set_ in ("practice", "sandbox"):
                pull(client, set_)
        page = build(None if args.offline else client)
        print(f"open {page}")
        return open_page(page)
    if args.cmd == "autoprobe":
        return autoprobe(client, args)
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


def autoprobe(client, args):
    package = DataPackage(args.data) if args.data else None

    def one(case_id):
        try:
            a = AutoProbe(client, case_id, package)
            result = a.run()
            path = save(client, a.table.session_id, probe=a.log)
            return case_id, f"{probe_summary(result)} -> {path}"
        except Exception as e:  # one broken case must not stop the others
            logging.exception("%s failed", case_id)
            return case_id, repr(e)

    with ThreadPoolExecutor(min(args.parallel, 10)) as pool:
        for case_id, line in pool.map(one, args.case_ids):
            print(case_id, line, flush=True)
    print(f"session page: {build(client)}")


if __name__ == "__main__":
    main()
