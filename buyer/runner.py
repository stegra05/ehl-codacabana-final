"""Plays cases with the policy. The arena answers one call per session at a time and each thread's
60-second clock runs from the supplier's reply, so one loop sends one message at a time, always to
the thread whose clock has run longest; finished threads get a short question before their clock
runs out while the others still negotiate; then the cheapest acceptable sheet is accepted.
`play_waves` is the kit's Live Final loop with this runner."""

import functools
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from arena_kit.client import ArenaError
from arena_kit.play import ENDED, RemoteTable, fetch_documents, latest, moves_left, quota_used_up

from .policy import Negotiator, deadline_near, keepalive_message

log = logging.getLogger("buyer")
RUNS = Path("logs/runs")
KEEPALIVE_AFTER_S = 35  # a finished thread gets a question this long after the supplier's reply


def play_case(table, case_id, pkg=None, deadline=None):
    case, threads = table.open(case_id)
    if getattr(table, "done", None):  # resumed a case that had already ended
        return table.done
    for events in threads.values():
        for m in events:
            fetch_documents(table, m)
    neg = Negotiator(case, pkg)
    for sid, events in threads.items():
        neg.setup(sid, events)
    replied = {sid: time.monotonic() for sid in threads}
    # round 1 goes out cheapest quote first: if a clock runs out, it is the least promising one's
    order = sorted(threads, key=lambda sid: neg.sides[sid].quote or float("inf"))
    rank = {sid: i for i, sid in enumerate(order)}
    result = None

    def open_threads():
        return [s for s in threads if neg.sides[s].state not in ("done", "ended") and live(s)]

    def live(sid):
        return latest(threads[sid]).get("status") not in ENDED

    while not deadline_near(deadline):
        todo = sorted(open_threads(), key=lambda s: (replied[s], rank[s]))
        waiting = [
            s
            for s in threads
            if neg.sides[s].state == "done"
            and live(s)
            and todo
            and time.monotonic() - replied[s] > KEEPALIVE_AFTER_S
            and moves_left(case, threads[s]) > 0
        ]
        if not todo:
            break
        if waiting:  # a finished bidder whose clock runs out first: keep it alive
            sid = min(waiting, key=lambda s: replied[s])
            message = keepalive_message(threads[sid])
        else:
            sid = todo[0]
            move = neg.move(sid, threads)
            if move is None:
                continue
            message = move["message"]
        try:
            reply = table.send(sid, message)
        except ArenaError as e:
            if e.status != 409:
                raise
            log.info("%s %s: %s", case_id, sid, e.detail)
            neg.rollback(sid)  # it never got this message: our last offer stands for it
            reply = table.missed(sid, e)
            if "result" in reply:
                result = reply["result"]
                break
            threads[sid].append(reply)
            replied[sid] = time.monotonic()
            continue
        neg.commit(sid)
        threads[sid] += [{**message, "from": "buyer"}, reply]
        replied[sid] = time.monotonic()
    if result is None:
        for events in threads.values():  # the latest quote PDFs: standard terms for the close
            for m in events[-2:]:
                try:
                    fetch_documents(table, m)
                except ArenaError as e:
                    log.warning("%s: document not fetched: %s", case_id, e)
        decision = neg.close(threads)
        try:
            result = table.close(decision["supplier_id"], decision["message"])
        except ArenaError as e:
            log.warning("%s: close failed (%s), accepting a standing sheet", case_id, e)
            result = table.close(*neg.fallback_close(threads))
    save(table.session_id, case_id, neg, result)
    return result


def save(session_id, case_id, neg, result):
    RUNS.mkdir(parents=True, exist_ok=True)
    keep = ("deal", "supplier_id", "terms", "c_open", "c_deal", "c_best", "score")
    path = RUNS / f"{case_id.split(':')[-1]}_{session_id}.json"
    out = {"case": case_id, "session": session_id, "notes": neg.notes, "result": {k: result.get(k) for k in keep}}
    path.write_text(json.dumps(out, indent=1, default=str))


def play_all(client, case_ids, pkg=None, parallel=8):
    """Practice or sandbox: many cases at once. {case_id: result or the exception that stopped it}."""
    used_up = threading.Event()

    def one(case_id):
        if used_up.is_set():
            return case_id, ArenaError(429, "not started: the practice quota is used up")
        try:
            return case_id, play_case(RemoteTable(client), case_id, pkg)
        except ArenaError as e:
            if quota_used_up(e):
                used_up.set()
            log.warning("%s: %s", case_id, e)
            return case_id, e
        except Exception as e:  # one broken case must not stop the others
            log.exception("%s failed", case_id)
            return case_id, e

    with ThreadPoolExecutor(max_workers=parallel) as pool:
        return dict(pool.map(one, case_ids))


def play_waves(client, pkg=None, waves=5, parallel=10, poll=5.0):
    """The Live Final: wait for each wave, play its cases in parallel within the wave's cap."""
    started, closed, caps = {}, set(), {}

    def one(case, deadline):
        try:
            return play_case(RemoteTable(client, case), case["case_id"], pkg, deadline)
        except Exception as e:  # one broken case must not stop the others
            log.exception("%s failed", case["case_id"])
            return e

    with ThreadPoolExecutor(max_workers=parallel) as pool:
        while len(closed) < waves or not all(f.done() for f in started.values()):
            try:
                cases = client.cases("final")
            except ArenaError as e:
                if e.status != 403:  # 403: no wave has started yet
                    raise
                cases = []
            for case in cases:
                if not case.get("open"):
                    closed.add(case["wave"])
                    continue
                if case.get("seconds_left") is not None:
                    caps[case["wave"]] = time.time() + case["seconds_left"]
                if case["case_id"] not in started and case.get("seconds_left"):
                    log.warning("wave %s: %s", case["wave"], case["case_id"])
                    started[case["case_id"]] = pool.submit(one, case, functools.partial(caps.get, case["wave"]))
            time.sleep(poll)
    return {case_id: f.result() for case_id, f in started.items()}
