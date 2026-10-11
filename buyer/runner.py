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
from arena_kit.play import (
    CLOSE_BEFORE_CAP_S,
    ENDED,
    ROUND_MARGIN_S,
    RemoteTable,
    fetch_documents,
    latest,
    moves_left,
    quota_used_up,
)

from . import llm, memory, research
from .policy import Negotiator, Side
from .writer import keepalive_message

log = logging.getLogger("buyer")
RUNS = Path("logs/runs")
KEEPALIVE_AFTER_S = 35  # a finished thread gets a question this long after the supplier's reply
CLOCK_S = 60  # each thread's clock, from the supplier's reply
MARGIN_S = 5  # reserved on every clock for building and delivering the message
FIRST_SEND_S = 10  # what a send (the supplier's reply) takes until we have measured one
CLOSE_TRIES = 3  # a 409 on the close: read what stands now and decide again
RETRY_S = 5  # a crashed final case is resumed after this long ...
RETRY_MARGIN_S = 120  # ... while its cap leaves at least this much to resume and close
RETRY_MAX = 40  # and never more often than this (a wave without a known cap)


def keepalive_due(age, send_s, writer_s):
    """Refresh a waiting offer before another model+send cycle can exhaust its supplier clock."""
    projected = age + max(0, writer_s) + send_s
    return age > KEEPALIVE_AFTER_S or projected >= CLOCK_S - MARGIN_S


def writer_budget(sid, replied, live, send_s, now):
    """Seconds the model may take on the message to `sid`: its own clock must not run out, and
    every other live thread must still get a message once this send returns."""
    left = [CLOCK_S - MARGIN_S - (now - replied[sid])]
    left += [CLOCK_S - MARGIN_S - send_s - (now - replied[o]) for o in live if o != sid]
    return min(llm.TIMEOUT_S, *left)


def play_case(table, case_id, pkg=None, deadline=None, complete=None, team=True, learn=True):
    """`team`: the research team briefs the bidder before the session opens (it needs the case file
    on `table.case`) and the live analyst reads every reply; off, the plain price engine plays.
    `learn`: the debrief writes this case's lesson for the next ones."""
    briefs = None
    if team and complete:
        briefs = safe_briefs(table.case, pkg, complete)
    opened = time.monotonic()  # the supplier clocks run from their first e-mail, before our setup
    case, threads = table.open(case_id)
    if getattr(table, "done", None):  # resumed a case that had already ended
        return table.done
    for events in threads.values():
        for m in events:
            fetch(table, case_id, m)
    neg = Negotiator(case, pkg, complete, briefs)
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

    slowest = 0.0  # the longest round so far, our move and the supplier's reply: a wave's cap must
    # leave room for one more of them, or a round started in time ends after the cap without a deal
    while not deadline_near(deadline, max(CLOSE_BEFORE_CAP_S, slowest + ROUND_MARGIN_S)):
        round_t0 = time.monotonic()
        neg.prune(threads)
        todo = sorted(open_threads(), key=lambda s: (replied[s], rank[s]))
        waiting = [
            s
            for s in threads
            if neg.sides[s].state == "done"
            and not neg.sides[s].dominated
            and live(s)
            and todo
            and replied[s] < replied[todo[0]]
            and keepalive_due(time.monotonic() - replied[s], send_s, llm.TIMEOUT_S)
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
            slowest = max(slowest, time.monotonic() - round_t0)
        except ArenaError as e:
            if e.status != 409:
                raise
            slowest = max(slowest, time.monotonic() - round_t0)
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
                fetch(table, case_id, m)
        result = close(table, case_id, neg, threads)
    save(table.session_id, case_id, neg, result)
    if learn and briefs is not None:
        try:
            memory.record(case, neg, result, complete)
        except Exception:  # the case is closed: a failed debrief costs nothing
            log.exception("%s: debrief failed", case_id)
    return result


def fetch(table, case_id, message):
    """A supplier message's attachments as text. One the arena does not deliver or the reader cannot
    parse is skipped: its terms then come from the e-mail and the case file, and the case goes on
    (unguarded, a broken quote PDF would crash every resumption of the case)."""
    try:
        fetch_documents(table, message)
    except Exception as e:  # noqa: BLE001 - a document must never cost the case
        log.warning("%s: document not read: %r", case_id, e)


def safe_briefs(case, pkg, complete):
    """The research team's briefs, or {} (no case file before the open, or the team failed): the
    live analyst still reads the replies."""
    if not case:
        return {}
    try:
        return research.briefs(case, pkg, complete)
    except Exception:  # the team must never cost the case
        log.exception("%s: research failed", case.get("case_id"))
        return {}


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


def play_all(client, cases, pkg=None, parallel=8, complete=None, team=True):
    """Practice or sandbox: many case files at once. {case_id: result or the exception that stopped it}."""
    used_up = threading.Event()
    files = {c["case_id"]: c for c in cases}
    model_metrics_before = llm.metrics_snapshot()

    def one(case_id):
        if used_up.is_set():
            return case_id, ArenaError(429, "not started: the practice quota is used up")
        try:
            table = PracticeTable(client, files[case_id])
            return case_id, play_case(table, case_id, pkg, complete=complete, team=team)
        except ArenaError as e:
            if quota_used_up(e):
                used_up.set()
            log.warning("%s: %s", case_id, e)
            return case_id, e
        except Exception as e:  # one broken case must not stop the others
            log.exception("%s failed", case_id)
            return case_id, e

    with ThreadPoolExecutor(max_workers=parallel) as pool:
        outcomes = dict(pool.map(one, files))
    log.info("model reliability across %d cases: %s", len(files), llm.metrics_since(model_metrics_before))
    return outcomes


class PracticeTable(RemoteTable):
    """A practice or sandbox table that knows its case file before the session opens, for the
    research team. Only the final resumes a running session, so a refused open raises as it is."""

    def open(self, case_id):
        r = self.client.open_session(case_id)
        self.session_id = r["session_id"]
        log.info("session %s", self.session_id)
        return r["case"], r["threads"]


def play_waves(client, pkg=None, waves=5, parallel=10, poll=2.0, complete=None, team=True):
    """The Live Final: wait for each wave, play its cases in parallel within the wave's cap. No
    human may restart it, so nothing here raises: a failed poll is polled again, a crashed case is
    resumed while its cap leaves time to close (the arena names the running session on a second
    open). The final writes no lessons: what the team knows was learned before it."""
    started, closed, caps = {}, set(), {}

    def one(case, deadline):
        attempt = 0
        while True:
            attempt += 1
            try:
                return play_case(RemoteTable(client, case), case["case_id"], pkg, deadline, complete, team, False)
            except Exception as e:  # noqa: BLE001 - one broken case must not stop the others
                log.exception("%s failed (attempt %d)", case["case_id"], attempt)
                err = e
            if attempt >= RETRY_MAX or deadline_near(deadline, RETRY_MARGIN_S):
                return err
            time.sleep(RETRY_S)

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


def deadline_near(deadline, margin=90):
    cap = deadline() if callable(deadline) else deadline
    return bool(cap) and time.time() > cap - margin
