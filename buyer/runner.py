"""Plays cases with the policy. Each supplier thread has its own worker that answers a reply at
once (every thread's 60-second clock runs on its own), finished threads are kept alive while the
others negotiate, then the cheapest acceptable sheet is accepted. Same hosted arena, sandbox,
practice or final; `play_waves` is the kit's Live Final loop with this runner."""

import functools
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from arena_kit.client import ArenaError
from arena_kit.play import ENDED, RemoteTable, fetch_documents, latest, moves_left, quota_used_up

from .policy import DONE, Negotiator, deadline_near, keepalive_message

log = logging.getLogger("buyer")
RUNS = Path("logs/runs")
KEEPALIVE_AFTER_S = 40  # a waiting thread gets a question this long after the supplier's reply
RESERVE = 2  # in an RFQ, messages a thread keeps for keepalives while the others negotiate


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
    lock, ended = threading.Lock(), threading.Event()
    rfq = len(threads) > 1
    replied = {sid: time.monotonic() for sid in threads}
    result = {}

    def send(sid, message):
        try:
            reply = table.send(sid, message)
        except ArenaError as e:
            if e.status != 409:
                raise
            log.info("%s %s: %s", case_id, sid, e.detail)
            reply = table.missed(sid, e)
            if "result" in reply:
                result.setdefault("r", reply["result"])
                ended.set()
                return False
        with lock:  # documents later: the session answers one call at a time and the clock runs
            threads[sid] += [{**message, "from": "buyer"}, reply]
            replied[sid] = time.monotonic()
        return True

    def all_done():
        with lock:
            return all(
                latest(ev).get("status") in ENDED | DONE or neg.sides[s].state != "open" for s, ev in threads.items()
            )

    def worker(sid):
        while not ended.is_set() and not deadline_near(deadline):
            with lock:
                if rfq and moves_left(case, threads[sid]) <= RESERVE:
                    neg.sides[sid].state = "done"
                    move = None
                else:
                    move = neg.move(sid, threads)
            if move is None or not send(sid, move["message"]):
                break
        while rfq and not ended.is_set() and not all_done() and not deadline_near(deadline):
            with lock:
                status = latest(threads[sid]).get("status")
                left = moves_left(case, threads[sid])
                waited = time.monotonic() - replied[sid]
            if status in ENDED:
                return
            if waited >= KEEPALIVE_AFTER_S and left > 0:
                if not send(sid, keepalive_message(threads[sid])):
                    return
            time.sleep(1)

    with ThreadPoolExecutor(max_workers=len(threads)) as pool:
        list(pool.map(worker, list(threads)))
    if result:
        out = result["r"]
    else:
        for events in threads.values():  # the latest quote PDFs: standard terms for the close
            for m in events[-2:]:
                try:
                    fetch_documents(table, m)
                except ArenaError as e:
                    log.warning("%s: document not fetched: %s", case_id, e)
        decision = neg.close(threads)
        out = table.close(decision["supplier_id"], decision["message"])
    save(table.session_id, case_id, neg, out)
    return out


def save(session_id, case_id, neg, result):
    RUNS.mkdir(parents=True, exist_ok=True)
    keep = ("deal", "supplier_id", "terms", "c_open", "c_deal", "c_best", "score")
    path = RUNS / f"{case_id.split(':')[-1]}_{session_id}.json"
    path.write_text(
        json.dumps(
            {"case": case_id, "session": session_id, "notes": neg.notes, "result": {k: result.get(k) for k in keep}},
            indent=1,
            default=str,
        )
    )


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
