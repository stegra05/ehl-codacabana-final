"""Plays a case with one negotiator per supplier thread, in parallel, so every thread answers
inside its own 60-second clock; a coordinator owns the decision to close. On top: the practice
runner and the Live Final wave runner, mirroring the kit's `play_all` and `play_waves`."""

import functools
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from arena_kit.client import ArenaError
from arena_kit.play import (
    CLOSE_BEFORE_CAP_S,
    ENDED,
    ROUND_MARGIN_S,
    RemoteTable,
    closing_move,
    fetch_documents,
    live_threads,
    quota_used_up,
    standing,
)

log = logging.getLogger("negotiator")


def play_case(table, case_id, agent, deadline=None):
    """One case to its end. `deadline`: a Live Final wave's cap (time.time(), or a function)."""
    case, threads = table.open(case_id)
    if getattr(table, "done", None):
        return table.done
    for events in threads.values():
        for m in events:
            fetch_documents(table, m)
    agent.prepare(case, threads)
    lock, done, box, slowest = threading.Lock(), threading.Event(), {}, [0.0]

    def close(sid, message):
        with lock:
            if done.is_set():
                return
            done.set()
            log.info("%s: closing via %s %s", case_id, sid, message.get("action"))
            try:
                box["result"] = table.close(sid, message)
            except ArenaError as e:
                if e.status != 409:
                    raise
                box["result"] = table.missed(sid, e).get("result") or table.result()

    def cap_near():
        cap = deadline() if callable(deadline) else deadline
        return bool(cap) and time.time() > cap - max(CLOSE_BEFORE_CAP_S, slowest[0] + ROUND_MARGIN_S)

    def worker(sid):
        while not done.is_set():
            if cap_near():
                log.warning("%s: the wave's cap is near - closing", case_id)
                d = closing_move(case, threads)
                close(d["supplier_id"], d["message"])
                return
            t0 = time.monotonic()
            try:
                d = agent.decide_thread(case, threads, sid)
            except Exception:  # a broken decision must not cost the case: the thread just stops
                log.exception("%s/%s: decide failed", case_id, sid)
                d = {"kind": "drop", "why": "error"}
            if done.is_set():
                return
            if d["kind"] == "drop":
                log.info("%s/%s: dropped (%s)", case_id, sid, d.get("why"))
                return
            if d["kind"] == "accept":
                best = agent.best_accept(case, threads)
                if best:
                    close(best["supplier_id"], best["message"])
                return
            msg = d["message"]
            try:
                reply = table.send(sid, msg)
            except ArenaError as e:
                if e.status == 422:  # the arena refused the message: nothing happened, send it without sheets
                    log.warning("%s/%s: 422 %s - resending without term sheets", case_id, sid, e.detail)
                    msg = {**msg, "term_sheets": []}
                    reply = table.send(sid, msg)
                elif e.status == 409:
                    reply = table.missed(sid, e)
                    if "result" in reply:
                        box["result"] = reply["result"]
                        done.set()
                        return
                else:
                    raise
            if "result" in reply:
                box["result"] = reply["result"]
                done.set()
                return
            threads[sid] += [{**msg, "from": "buyer"}, fetch_documents(table, reply)]
            slowest[0] = max(slowest[0], time.monotonic() - t0)
            log.info("%s/%s: %s %s", case_id, sid, reply.get("status"), standing(threads[sid])[1])
            if reply.get("status") in ENDED:
                return

    workers = [threading.Thread(target=worker, args=(sid,), name=f"{case_id}/{sid}", daemon=True) for sid in threads]
    for t in workers:
        t.start()
    for t in workers:
        t.join()
    if "result" not in box and not done.is_set():
        best = agent.best_accept(case, threads)
        live = live_threads(threads)
        if best:
            close(best["supplier_id"], best["message"])
        elif live:
            close(live[0], {"action": {"type": "walk_away"}})
    result = box.get("result") or table.result()
    replay = None
    try:
        replay = table.client.session(table.session_id).get("replay_url")
    except Exception:  # the replay link is a courtesy, never a reason to fail
        replay = None
    try:
        agent.after_case(case, threads, result, replay)
    except Exception:
        log.exception("%s: learning step failed", case_id)
    result["replay_url"] = replay
    return result


def play_all(client, case_ids, new_agent, parallel=8):
    """Every listed case at once, one agent each; stops starting cases once the practice quota is gone."""
    used_up = threading.Event()

    def one(case_id):
        if used_up.is_set():
            return case_id, ArenaError(429, "not started: the practice quota is used up")
        try:
            return case_id, play_case(RemoteTable(client), case_id, new_agent())
        except ArenaError as e:
            if quota_used_up(e):
                used_up.set()
            log.warning("%s: %s", case_id, e.detail)
            return case_id, e
        except Exception as e:
            log.exception("%s failed", case_id)
            return case_id, e

    with ThreadPoolExecutor(max_workers=parallel) as pool:
        return dict(pool.map(one, case_ids))


def play_waves(client, new_agent, waves=5, parallel=10, poll=5.0):
    """The Live Final: wait for each wave, play its cases in parallel within the cap, stop after the last."""
    started, closed, caps = {}, set(), {}

    def one(case, deadline):
        try:
            return play_case(RemoteTable(client, case), case["case_id"], new_agent(), deadline)
        except Exception as e:
            log.exception("%s failed", case["case_id"])
            return e

    with ThreadPoolExecutor(max_workers=parallel) as pool:
        while len(closed) < waves or not all(f.done() for f in started.values()):
            try:
                cases = client.cases("final")
            except ArenaError as e:
                if e.status != 403:
                    raise
                cases = []
            for case in cases:
                if not case.get("open"):
                    closed.add(case["wave"])
                    continue
                if case.get("seconds_left") is not None:
                    caps[case["wave"]] = time.time() + case["seconds_left"]
                if case["case_id"] not in started and case.get("seconds_left"):
                    if case["wave"] not in {c["wave"] for c in cases if c["case_id"] in started}:
                        log.warning("wave %s started: %s", case["wave"], case.get("theme"))
                    started[case["case_id"]] = pool.submit(one, case, functools.partial(caps.get, case["wave"]))
            time.sleep(poll)
    return {case_id: f.result() for case_id, f in started.items()}
