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

from . import llm
from .policy import Negotiator, Side, deadline_near, keepalive_message

log = logging.getLogger("buyer")
RUNS = Path("logs/runs")
KEEPALIVE_AFTER_S = 35  # a finished thread gets a question this long after the supplier's reply
CLOCK_S = 60  # each thread's clock, from the supplier's reply
MARGIN_S = 5  # reserved on every clock for building and delivering the message
FIRST_SEND_S = 10  # what a send (the supplier's reply) takes until we have measured one
CLOSE_TRIES = 3  # a 409 on the close: read what stands now and decide again


def writer_budget(sid, replied, live, send_s, now):
    """Seconds the model may take on the message to `sid`: its own clock must not run out, and
    every other live thread must still get a message once this send returns."""
    left = [CLOCK_S - MARGIN_S - (now - replied[sid])]
    left += [CLOCK_S - MARGIN_S - send_s - (now - replied[o]) for o in live if o != sid]
    return min(llm.TIMEOUT_S, *left)


def play_case(table, case_id, pkg=None, deadline=None, complete=None):
    opened = time.monotonic()  # the supplier clocks run from their first e-mail, before our setup
    case, threads = table.open(case_id)
    if getattr(table, "done", None):  # resumed a case that had already ended
        return table.done
    for events in threads.values():
        for m in events:
            fetch_documents(table, m)
    neg = Negotiator(case, pkg, complete)
    for sid, events in threads.items():
        try:
            neg.setup(sid, events)
            if any(m.get("from") == "buyer" for m in events):  # resumed: continue the path
                neg.restore(sid, events)
        except Exception:  # one supplier's data must not lose the case
            log.exception("%s %s: setup failed", case_id, sid)
            neg.sides.setdefault(sid, Side(sid)).state = "done"
    failed = dict.fromkeys(threads, 0)
    replied = dict.fromkeys(threads, opened)
    send_s = FIRST_SEND_S  # the slowest send so far
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
            and moves_left(case, threads[s]) - neg.sides[s].late > 0
        ]
        if not todo:
            break
        if waiting:  # a finished bidder whose clock runs out first: keep it alive
            sid = min(waiting, key=lambda s: replied[s])
            message = keepalive_message(threads[sid])
        else:
            sid = todo[0]
            budget = writer_budget(sid, replied, [s for s in threads if live(s)], send_s, time.monotonic())
            try:
                move = neg.move(sid, threads, budget)
            except Exception:  # a field the policy did not expect: the thread must not fall silent
                log.exception("%s %s: move failed", case_id, sid)
                failed[sid] += 1
                if failed[sid] > 2:
                    neg.sides[sid].state = "done"
                    continue
                move = neg.fallback_move(sid, threads)
            if move is None:
                continue
            message = move["message"]
        t0 = time.monotonic()
        try:
            reply = table.send(sid, message)
            send_s = max(send_s, time.monotonic() - t0)
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
        if "result" in reply:  # the reply ended the case, e.g. the last supplier walked away
            result = reply["result"]
            break
        threads[sid] += [{**message, "from": "buyer"}, reply]
        replied[sid] = time.monotonic()
    if result is None:
        for events in threads.values():  # the latest quote PDFs: standard terms for the close
            for m in events[-2:]:
                try:
                    fetch_documents(table, m)
                except ArenaError as e:
                    log.warning("%s: document not fetched: %s", case_id, e)
        result = close(table, case_id, neg, threads)
    save(table.session_id, case_id, neg, result)
    return result


def close(table, case_id, neg, threads):
    """Accept or walk away. A 409 (the sheet expired, the thread ended) means the arena state moved:
    read what stands now and decide again with the same guards. Anything else raises, and the Live
    Final loop resumes the case."""
    for _ in range(CLOSE_TRIES):
        decision = neg.close(threads)
        sid = decision["supplier_id"]
        try:
            return table.close(sid, decision["message"])
        except ArenaError as e:
            if e.status != 409:
                raise
            log.info("%s %s: close refused: %s", case_id, sid, e.detail)
            reply = table.missed(sid, e)
            if "result" in reply:
                return reply["result"]
            threads[sid].append(reply)
    raise RuntimeError(f"{case_id}: no close after {CLOSE_TRIES} tries")


def save(session_id, case_id, neg, result):
    RUNS.mkdir(parents=True, exist_ok=True)
    keep = ("deal", "supplier_id", "terms", "c_open", "c_deal", "c_best", "score")
    path = RUNS / f"{case_id.split(':')[-1]}_{session_id}.json"
    out = {"case": case_id, "session": session_id, "notes": neg.notes, "result": {k: result.get(k) for k in keep}}
    path.write_text(json.dumps(out, indent=1, default=str))


def play_all(client, case_ids, pkg=None, parallel=8, complete=None):
    """Practice or sandbox: many cases at once. {case_id: result or the exception that stopped it}."""
    used_up = threading.Event()

    def one(case_id):
        if used_up.is_set():
            return case_id, ArenaError(429, "not started: the practice quota is used up")
        try:
            return case_id, play_case(RemoteTable(client), case_id, pkg, complete=complete)
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


def play_waves(client, pkg=None, waves=5, parallel=10, poll=2.0, complete=None):
    """The Live Final: wait for each wave, play its cases in parallel within the wave's cap. No
    human may restart it, so nothing here raises: a failed poll is polled again, a crashed case is
    resumed once (the arena names the running session on a second open)."""
    started, closed, caps = {}, set(), {}

    def one(case, deadline):
        for attempt in range(2):
            try:
                return play_case(RemoteTable(client, case), case["case_id"], pkg, deadline, complete)
            except Exception as e:  # noqa: BLE001 - one broken case must not stop the others
                log.exception("%s failed (attempt %d)", case["case_id"], attempt + 1)
                err = e
                time.sleep(2)
        return err

    with ThreadPoolExecutor(max_workers=parallel) as pool:
        while len(closed) < waves or not all(f.done() for f in started.values()):
            try:
                cases = client.cases("final")
            except Exception as e:  # noqa: BLE001 - 403 before the first wave, a network blip: poll again
                if not (isinstance(e, ArenaError) and e.status == 403):
                    log.warning("case list: %s", e)
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
