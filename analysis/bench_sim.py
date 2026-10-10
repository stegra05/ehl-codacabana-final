"""Benchmark on arena-sim: every case file (practice and sandbox) played in-process by the code
policy and by the reasoner, side by side. The sim's supplier is a fixed script (a step per sheet
down to a floor, agreement at or above its next price, a final offer late), so this compares
mechanics and model latency, not tactics against the arena's bots. No quota, no network beyond
the model endpoint.

  uv run python analysis/bench_sim.py            # code policy, reasoner with a fake model
  uv run python analysis/bench_sim.py --model    # plus the reasoner with the configured model
"""

import argparse
import json
import logging
import secrets
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from arena_kit import ArenaClient, RemoteTable
from arena_kit.cli import load_env
from arena_kit.sim import Sim

sys.path.insert(0, str(Path(__file__).parent.parent / "tests"))
from conftest import serve  # noqa: E402

from buyer import llm, runner  # noqa: E402
from buyer.policy import Negotiator  # noqa: E402
from buyer.reasoner import Reasoner  # noqa: E402

CASES = Path(__file__).parent.parent / "logs" / "cases"
# Best practice score per hosted case so far (the arena, logs/sessions), for context only
ARENA_BEST = {
    "P01": 1.00, "P02": 0.735, "P03": 0.93, "P04": 0.86, "P05": 0.83,
    "P07": 0.76, "P08": 0.67, "P10": 0.69, "P11": 0.71, "P18": 0.69,
}  # fmt: skip


def all_cases():
    out = {}
    for path in sorted(CASES.glob("*.json")):
        for case in json.loads(path.read_text()):
            out[case["case_id"]] = {k: v for k, v in case.items() if k != "hosted"}
    return out


def fake_model(system, user):
    if "OPTIONS" not in user:
        return json.dumps({"asks": [], "levers": [], "counted": [], "dismissed": []})
    trade = next((line.split(":", 1)[0].strip("- ") for line in user.split("\n") if line.startswith("- trade:")), None)
    return json.dumps({"option": trade or "step", "claims": 1, "reason": "bench"})


def play(client, cases, negotiator, complete, parallel=8):
    runner.RUNS = Path("logs/bench")
    runs = {}

    def one(case_id):
        t0 = time.monotonic()
        try:
            result = runner.play_case(RemoteTable(client), case_id, None, None, complete, negotiator)
            return case_id, result.get("score"), result.get("deal"), time.monotonic() - t0
        except Exception as e:  # noqa: BLE001 - the bench reports the failure
            return case_id, None, f"error: {e}", time.monotonic() - t0

    with ThreadPoolExecutor(max_workers=parallel) as pool:
        for case_id, score, deal, secs in pool.map(one, sorted(cases)):
            runs[case_id] = (score, deal, secs)
    return runs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", action="store_true", help="also run the reasoner with the configured model")
    ap.add_argument("--parallel", type=int, default=8)
    args = ap.parse_args()
    load_env()
    logging.basicConfig(level=logging.WARNING)
    cases = all_cases()
    columns = [("code policy", Negotiator, None), ("reasoner, fake model", Reasoner, fake_model)]
    if args.model:
        complete = llm.complete_from_env()
        if complete is None:
            raise SystemExit("no model configured (LLM_MODEL, LLM_API_KEY)")
        columns.append(("reasoner, model", Reasoner, complete))
    results = {}
    with serve(Sim(cases, clock=lambda: 1_000_000.0)) as url:
        for name, negotiator, complete in columns:
            key = ArenaClient(url).register(f"bench-{secrets.token_hex(3)}", "sim")["api_key"]
            client = ArenaClient(url, key, rate=1000)
            t0 = time.monotonic()
            results[name] = play(client, cases, negotiator, complete, args.parallel)
            print(f"{name}: {time.monotonic() - t0:.0f} s", file=sys.stderr)
    head = f"{'case':10}" + "".join(f"{n:>24}" for n, _, _ in columns) + f"{'arena best':>12}"
    print(head)
    for case_id in sorted(cases):
        short = case_id.split(":")[-1]
        row = f"{short:10}"
        for name, _, _ in columns:
            score, deal, secs = results[name][case_id]
            cell = f"{score:.3f}" if score is not None else str(deal)[:14]
            row += f"{cell:>19} {secs:4.0f}s"
        row += f"{ARENA_BEST.get(short, ''):>12}"
        print(row)
    print(f"{'mean':10}", end="")
    for name, _, _ in columns:
        scores = [s for s, _, _ in results[name].values() if s is not None]
        print(f"{statistics.mean(scores):>19.3f}      ", end="")
    print()
    hosted = [c for c in ARENA_BEST]
    print(f"{'mean hosted':10}", end="")
    for name, _, _ in columns:
        scores = [results[name][f"case:{c}"][0] for c in hosted if results[name][f"case:{c}"][0] is not None]
        print(f"{statistics.mean(scores):>19.3f}      ", end="")
    print(f"{statistics.mean(ARENA_BEST.values()):>12.3f}")


if __name__ == "__main__":
    main()
