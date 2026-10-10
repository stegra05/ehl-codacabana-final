"""`negotiator`: play a case, run a set (practice, sandbox, the Live Final), manage the persona
knowledge base. Reads `.env` like the kit does."""

import argparse
import functools
import json
import logging
import os
import statistics

from arena_kit.cli import load_env, summary
from arena_kit.client import ArenaClient, ArenaError
from arena_kit.data import DataPackage
from arena_kit.play import RemoteTable, hosted

from . import llm as llm_mod
from . import personas, runner
from .agent import Negotiator

DATA_DEFAULT = "negotiation-agent/negotiation-arena-kit/data"


def package(path=None):
    p = path or os.environ.get("ARENA_DATA") or DATA_DEFAULT
    try:
        pkg = DataPackage(p)
    except FileNotFoundError:
        print(f"no data package at {p}: personas and claims will be thin")
        return None
    pkg.lookup("")  # build the ID index once, before agents share it
    return pkg


def main(argv=None):
    load_env()
    ap = argparse.ArgumentParser(prog="negotiator")
    ap.add_argument("-v", "--verbose", action="store_true")
    verbose = argparse.ArgumentParser(add_help=False)  # -v also after the command
    verbose.add_argument("-v", "--verbose", action="store_true", default=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser = functools.partial(sub.add_parser, parents=[verbose])
    p = sub.add_parser("play", help="play one case")
    p.add_argument("case_id")
    p.add_argument("--data", default=None)
    p.add_argument("--no-llm", action="store_true", help="template e-mails only")
    r = sub.add_parser("run", help="play a whole set in parallel; --set final waits for the waves")
    r.add_argument("--set", default="practice", help="practice, sandbox or final")
    r.add_argument("--parallel", type=int, default=8)
    r.add_argument("--waves", type=int, default=5)
    r.add_argument("--data", default=None)
    r.add_argument("--no-llm", action="store_true")
    k = sub.add_parser("kb", help="the supplier persona knowledge base")
    ks = k.add_subparsers(dest="kb_cmd", required=True)
    b = ks.add_parser("build", help="build every persona from the data package")
    b.add_argument("--llm", action="store_true", help="also digest each supplier's notes with the model")
    b.add_argument("--only", help="one supplier id, e.g. sup:70110")
    b.add_argument("--data", default=None)
    s = ks.add_parser("show", help="print one persona")
    s.add_argument("supplier_id")
    ks.add_parser("index", help="rewrite knowledge/personas/README.md")
    args = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING, format="%(asctime)s %(message)s", datefmt="%H:%M:%S"
    )

    if args.cmd == "kb":
        return kb(args)
    pkg = package(args.data)
    llm = None if args.no_llm else llm_mod.from_env()
    if llm is None and not args.no_llm:
        print("no ANTHROPIC_API_KEY: template e-mails only")
    client = ArenaClient()
    url = os.environ.get("ARENA_URL", "")
    learn = not ("127.0.0.1" in url or "localhost" in url)  # arena-sim teaches the contract, not the suppliers
    if not learn:
        print("local simulator: personas are not updated")

    def new_agent():
        return Negotiator(pkg, llm, kb=learn)

    if args.cmd == "play":
        table = RemoteTable(client)
        try:
            result = runner.play_case(table, args.case_id, new_agent())
        except ArenaError as e:
            raise SystemExit(str(e)) from None
        print(json.dumps(summary(result), indent=2))
        if result.get("replay_url"):
            print(f"replay: {os.environ.get('ARENA_URL', '').rstrip('/')}{result['replay_url']}")
    elif args.set == "final":
        out = runner.play_waves(client, new_agent, args.waves, min(args.parallel, 10))
        report(client, out, final=True)
    else:
        ids = [c["case_id"] for c in hosted(client.cases(args.set))]
        out = runner.play_all(client, ids, new_agent, min(args.parallel, 10))
        report(client, out)
    if client.practice_remaining is not None:
        print(f"practice sessions left today: {client.practice_remaining}")


def report(client, out, final=False):
    for case_id, result in out.items():
        print(case_id, result if isinstance(result, Exception) else summary(result))
    scores = {c: r.get("score") for c, r in out.items() if isinstance(r, dict)}
    if final and scores:
        waves = {}
        for case in client.cases("final"):
            waves.setdefault(case["wave"], []).append(scores.get(case["case_id"]) or 0)
        points = {n: round(100 * statistics.mean(v), 1) for n, v in sorted(waves.items())}
        print(f"waves: {points}  points so far: {round(sum(points.values()), 1)}")
    elif scores and all(v is not None for v in scores.values()):
        print(f"mean score: {100 * statistics.mean(scores.values()):.1f}")


def kb(args):
    if args.kb_cmd == "show":
        persona = personas.load(args.supplier_id)
        if not persona:
            raise SystemExit(f"no persona for {args.supplier_id}: run `negotiator kb build`")
        print(json.dumps(persona, indent=1, ensure_ascii=False))
        return
    if args.kb_cmd == "index":
        print(f"{personas.write_index()} personas indexed")
        return
    pkg = package(args.data)
    if pkg is None:
        raise SystemExit("the knowledge base is built from the data package")
    llm = llm_mod.from_env() if args.llm else None
    if args.llm and llm is None:
        raise SystemExit("--llm needs ANTHROPIC_API_KEY")
    ids = (
        [args.only]
        if args.only
        else [r["id"] for r in pkg.query("SELECT id FROM suppliers WHERE detail = 'full' ORDER BY id")]
    )
    for sid in ids:
        old = personas.load(sid)
        persona = personas.build(pkg, sid, llm)
        if old:  # keep what we learned in practice
            persona["learned"], persona["negotiations"] = (
                old.get("learned", persona["learned"]),
                old.get("negotiations", []),
            )
            if old.get("digest") and not persona.get("digest"):
                persona["digest"] = old["digest"]
            personas.refresh(persona)
        personas.save(persona)
        print(
            f"{sid}  {persona['name'][:34]:34}  {persona['importance']['tier']:9}  "
            f"{persona['archetype']:16}  {persona['tone']:7}  {', '.join(persona['levers'][:2])}"
        )
    print(f"{personas.write_index()} personas in {personas.KB_DIR}")


if __name__ == "__main__":
    main()
