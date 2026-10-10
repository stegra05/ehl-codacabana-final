"""`buyer` command line: play one case or a whole set with our agent, print the plan for a case
without opening a session, and pull finished sessions (result, trace with the supplier's reasons,
back office) into logs/ for the learning loop."""

import argparse
import functools
import json
import logging
import os
import statistics
from pathlib import Path

from arena_kit import ArenaClient, ArenaError, RemoteTable, play
from arena_kit.cli import load_env, summary
from arena_kit.play import hosted

from . import economics, runner
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


def data_dir():
    """ARENA_DATA when it holds a package, else data/package (`uv run arena data`), else None."""
    for d in (os.environ.get("ARENA_DATA"), "data/package"):
        if d and (Path(d) / "facts.json").is_file():
            return d
    logging.getLogger("buyer").warning("no data package found: run `uv run arena data`")
    return None


def plan(client, case_id, new_agent):
    """The case brief without a session: persona, floor, anchor, target, levers, claims."""
    set_ = "sandbox" if case_id.split(":")[-1].startswith("D") else "practice"
    case = next((c for c in client.cases(set_) if c["case_id"] == case_id), None)
    if not case:
        raise SystemExit(f"{case_id}: not in the {set_} case list")
    agent = new_agent()
    agent.prepare(case, {})
    for sid, p in agent.plan.items():
        persona = p["persona"]
        print(
            f"\n{sid} {persona['name']}: {persona['archetype']} ({persona.get('secondary') or '-'}), "
            f"tier {persona['importance']['tier']}, tone {persona['tone']}"
        )
        for s in persona["signals"]:
            print(f"  signal: {s}")
        st = p["stance"]
        print(
            f"  stance ({st['source']}): gap {st['opening_gap']:.2f}, capture {st['capture']:.2f}, "
            f"margin {st['margin_pct']:.1f}%, quote margin {st['quote_margin_pct']:.0f}%, "
            f"steps {st['steps']}, close {st['close_step']:.2f}"
        )
        if st.get("reason"):
            print(f"  reason: {st['reason']}")
        est = p["est"] or {}
        print(
            f"  full cost {est.get('full_cost')} ({est.get('source')})  floor {p['floor']}  anchor {p['anchor']}  "
            f"c_open {p['c_open']:,.0f}  target {p['target']:,.0f}  "
            f"justified {p['justified_pct']}%  asked {p['asked_pct']}%"
        )
        print(f"  levers: {', '.join(p['levers'])}")
        for r in p["analysis"]:
            print(f"  lever {economics.lever_line(r)}")
        for c in p["claims"][:8]:
            print(f"  claim [{c['strength']:.1f}{'' if c['for_us'] else ' not for us'}] {c['sentence']}")


def main(argv=None):
    load_env()
    ap = argparse.ArgumentParser(prog="buyer")
    ap.add_argument("-v", "--verbose", action="store_true")
    verbose = argparse.ArgumentParser(add_help=False)  # -v also after the command
    verbose.add_argument("-v", "--verbose", action="store_true", default=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser = functools.partial(sub.add_parser, parents=[verbose])
    data = {"default": data_dir(), "help": "data package folder"}
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
    q = sub.add_parser("plan", help="print the case brief without opening a session (no quota)")
    q.add_argument("case_id")
    q.add_argument("--data", **data)
    q.add_argument("--no-model", action="store_true", help="the default stance instead of the model's")
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
    if args.cmd == "plan":
        return plan(client, args.case_id, agent_factory("buyer", args.data, model=False if args.no_model else None))
    new_agent = agent_factory(args.agent, args.data)
    ours = args.agent == "buyer"
    if args.cmd == "play":
        table = RemoteTable(client)
        try:
            result = (runner.play_case if ours else play)(table, args.case_id, new_agent())
        except ArenaError as e:  # e.g. not hosted, the quota, a paused key: the arena says why
            raise SystemExit(str(e)) from None
        print(json.dumps(summary(result), indent=2))
        state = client.session(table.session_id)
        print(f"replay: {os.environ['ARENA_URL'].rstrip('/')}{state.get('replay_url')}")
        pull(client, state["set"])
    elif args.set == "final":  # no human in the loop: waits for each wave, plays it within its cap
        out = runner.play_waves(client, new_agent, args.waves, min(args.parallel, 10))
        for case_id, result in out.items():
            print(case_id, result if isinstance(result, Exception) else summary(result))
    else:
        ids = [c["case_id"] for c in hosted(client.cases(args.set))]
        out = runner.play_all(client, ids, new_agent, min(args.parallel, 10))
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
