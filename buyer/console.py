"""Operator console for probing practice cases: a person picks each move from options built in code.

One worker per supplier thread waits for the supplier's reply, builds the options and queues a
decision. The terminal shows the reply and the options; the operator types a number. If nobody
picks within `auto_after` seconds of the reply, the worker sends the first option itself, so a slow
pick never becomes a timeout (the arena allows 60 s). Every move is logged with what it tests,
whether it was picked or sent automatically, and how long the pick took.
"""

import json
import queue
import select
import sys
import threading
import time
from dataclasses import dataclass, field

from arena_kit import ArenaError, RemoteTable
from arena_kit.cost import total_cost
from arena_kit.docs import standard_terms
from arena_kit.play import ENDED, fetch_documents, latest, moves_left, standing

from .moves import Option, Prober

AUTO_AFTER_S = 45.0
SUGGEST_TIMEOUT_S = 20.0
DOC_LINES = 40


@dataclass
class Pending:
    supplier_id: str
    options: list
    born: float
    choice: Option | None = None
    auto: bool = False
    picked_at: float | None = None
    ai: list = field(default_factory=list)
    ai_state: str = "off"  # off, thinking, ready, failed
    lock: threading.Lock = field(default_factory=threading.Lock)
    done: threading.Event = field(default_factory=threading.Event)


class Console:
    def __init__(
        self, client, case_id, package=None, auto_after=AUTO_AFTER_S, interactive=True, out=print, suggester=None
    ):
        self.client, self.case_id, self.package, self.suggester = client, case_id, package, suggester
        self.auto_after, self.interactive, self.out = auto_after, interactive, out
        self.table = RemoteTable(client)
        self.decisions = queue.Queue()
        self.over = threading.Event()
        self.lock = threading.Lock()
        self.log, self.result = [], None

    # ---------- the session ----------

    def run(self):
        self.case, self.threads = self.table.open(self.case_id)
        for events in self.threads.values():
            for m in events:
                fetch_documents(self.table, m)
        self.prober = Prober(self.case, self.package)
        self.out(self._brief())
        workers = [threading.Thread(target=self._worker, args=(s,), daemon=True) for s in self.threads]
        for w in workers:
            w.start()
        while not self.over.is_set() and any(w.is_alive() for w in workers):
            try:
                p = self.decisions.get(timeout=0.5)
            except queue.Empty:
                continue
            self._decide(p)
        for w in workers:
            w.join(timeout=200)
        return self.result or self.table.result()

    def _worker(self, sid):
        try:
            while not self.over.is_set():
                with self.lock:
                    events = list(self.threads[sid])
                if latest(events).get("status") in ENDED:
                    return
                p = Pending(sid, self.prober.options(sid, self.threads), time.monotonic())
                if self.suggester:
                    p.ai_state = "thinking"
                    threading.Thread(target=self._suggest, args=(p,), daemon=True).start()
                self.decisions.put(p)
                p.done.wait(max(0.0, self.auto_after - (time.monotonic() - p.born)))
                with p.lock:
                    if p.choice is None:
                        p.choice, p.auto, p.picked_at = p.options[0], True, time.monotonic()
                if not self._send(sid, p):
                    return
        except Exception as e:  # one broken thread must not hang the console
            self.out(f"!! {sid}: {e!r}")

    def _suggest(self, p):
        """Ask the model for suggestions; shown only if they arrive within SUGGEST_TIMEOUT_S."""
        try:
            with self.lock:
                threads = {k: list(v) for k, v in self.threads.items()}
            ai = self.suggester.suggest(self.case, p.supplier_id, threads, self.prober)
            late = time.monotonic() - p.born > SUGGEST_TIMEOUT_S
            p.ai, p.ai_state = ([], "failed: too slow") if late else (ai, "ready")
        except Exception as e:
            p.ai_state = f"failed: {e!r}"[:120]

    def _send(self, sid, p):
        """Send the chosen move; False once this thread or the case has ended."""
        o, events = p.choice, self.threads[sid]
        self.prober.sent(sid, o)
        self.log.append(
            {
                "supplier_id": sid,
                "round": self.case.get("round_limit", 10) - moves_left(self.case, events) + 1,
                "key": o.key,
                "note": o.note,
                "auto": p.auto,
                "decide_s": round(p.picked_at - p.born, 1),
                "costs": o.costs,
                "claims": o.claims,
                "levers": o.levers,
                "message": o.message,
            }
        )
        if p.auto:
            self.out(f"\n>> {sid}: sent the default '{o.key}' automatically")
        try:
            reply = self.client.send_message(self.table.session_id, sid, o.message)
        except ArenaError as e:
            if e.status != 409:
                raise
            reply = self.table.missed(sid, e)
        if "result" in reply or o.message.get("action"):
            self.result = reply.get("result", reply)
            self.over.set()
            return False
        fetch_documents(self.table, reply)
        with self.lock:
            self.threads[sid] = [*self.threads[sid], {**o.message, "from": "buyer"}, reply]
        return reply.get("status") not in ENDED

    # ---------- the terminal ----------

    def _decide(self, p):
        if p.choice is not None:
            return
        self.out(self._render(p))
        choice = self._pick(p) if self.interactive else p.options[0]
        with p.lock:
            if p.choice is None and choice is not None:
                p.choice, p.picked_at = choice, time.monotonic()
                p.done.set()
            elif choice is not None:
                self.out(">> too late: the default went out")

    def _pick(self, p):
        deadline, shown, asked = p.born + self.auto_after, "off", False
        while (left := deadline - time.monotonic()) > 0 and p.choice is None:
            if p.ai_state != shown and p.ai_state != "thinking":
                shown, asked = p.ai_state, False
                self.out(self._render_ai(p))
            if not asked:
                self.out(
                    f"[{p.supplier_id}] pick 1-{len(p.options)}{', a1-a3' if p.ai else ''}, 'p <price>', "
                    f"'q <question>' (Enter = 1, auto in {left:.0f}s"
                    f"{', AI thinking' if p.ai_state == 'thinking' else ''}): "
                )
                asked = True
            ready, _, _ = select.select([sys.stdin], [], [], min(left, 0.5))
            if not ready:
                continue
            choice = self._parse(p, sys.stdin.readline().strip())
            if choice:
                return choice
            self.out("?? not understood")
            asked = False
        return None

    def _render_ai(self, p):
        if not p.ai:
            return f"AI suggestions: {p.ai_state}"
        lines = ["AI suggestions:"]
        for o in p.ai:
            sheets = [s["terms"] for s in o.message.get("term_sheets", [])]
            costs = ", ".join(f"{x:,.0f}" for x in o.costs)
            lines.append(f" {o.key:3} {o.note[:90]}")
            lines.append(f"     {o.message.get('action') or ''}{json.dumps(sheets) if sheets else ''} C={costs}")
            body = (o.message.get("body") or "").strip().splitlines()
            lines += [f"     | {b}" for b in body[:8] if b.strip()]
        return "\n".join(lines)

    def _parse(self, p, line):
        if not line:
            return p.options[0]
        if line.isdigit() and 1 <= int(line) <= len(p.options):
            return p.options[int(line) - 1]
        if ai := next((o for o in p.ai if o.key == line), None):
            return ai
        events = self.threads[p.supplier_id]
        if line.startswith("p "):
            try:
                price = round(float(line[2:].replace(",", ".")), 2)
            except ValueError:
                return None
            base = next(o for o in p.options if o.key.startswith("step-"))
            sheet = {**base.message["term_sheets"][0]["terms"], "unit_price": price}
            return self.prober.option(f"price {price}", "operator price", "Our proposal is below.", [sheet], events)
        if line.startswith("q ") and line[2:].strip():
            return self.prober.option("question", f"operator: {line[2:60]}", line[2:].strip(), [], events)
        return None

    def _brief(self):
        c, b = self.case, self.case["buyer"]
        lines = [
            f"\n######## {c['case_id']} {c['title']} ({c['type']}, {b['category_goal']})",
            f"need {b['need_per_year']}/yr x {b['horizon_years']} yrs, current {b.get('current_unit_price')}, "
            f"fallback {b['fallback_unit_price']}, alternative C {self.prober.c_alt():,.0f}",
            f"negotiable {c['negotiable']}  fixed {c.get('fixed_terms')}  must-haves {b.get('must_haves')}",
        ]
        for sid in self.threads:
            lines.append(f"{sid}: should-cost {self.prober.should_cost(sid)}")
        return "\n".join(lines)

    def _render(self, p):
        sid, events = p.supplier_id, self.threads[p.supplier_id]
        m = latest(events)
        sheet_id, terms = standing(events)
        std = standard_terms(events)
        c = total_cost(self.case, terms, std) if sheet_id else None
        lines = [
            "\a\n" + "=" * 100,
            f"{sid} | {m.get('from')} | status {m.get('status')} | {moves_left(self.case, events)} messages left "
            f"| signals {m.get('signals')}",
            "-" * 100,
            (m.get("body") or "").strip(),
            "-" * 100,
        ]
        if m.get("claim_results"):
            lines.append(f"claims: {m['claim_results']}")
        if m.get("missing_fields"):
            lines.append(f"missing fields (close on standard terms): {m['missing_fields']}")
        for att in m.get("attachments") or []:
            text = (att.get("text") or "").strip().splitlines()
            lines += [f"[{att.get('name')}]", *("    " + t for t in text[:DOC_LINES])]
        lines.append(f"standing {sheet_id} {json.dumps(terms)}  C={c:,.0f}" if c else "no standing term sheet")
        if std:
            lines.append(f"standard terms {json.dumps(std)}")
        lines.append("options:")
        for i, o in enumerate(p.options, 1):
            costs = ", ".join(f"{x:,.0f}" for x in o.costs)
            prices = [s["terms"].get("unit_price") for s in o.message.get("term_sheets", [])]
            lines.append(f" {i:2}{'*' if i == 1 else ' '} {o.key:28.28} {o.note[:58]:58} {prices or ''} C={costs}")
        return "\n".join(lines)
