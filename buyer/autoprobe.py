"""Automatic probe of one practice case: a fixed experiment per supplier thread, then the best close.

Per thread, in order:
  open    questions and documents (cost breakdown, delivery schedule or 8D), our anchor price
  ours    up to 3 sheets at the supplier's price, each with ONE lever moved our way (later start,
          longer payment, full coverage, DAP, ...): which of them does it give for free, at what price?
  theirs  up to 3 sheets a step below, each with ONE lever moved its way, cheapest for us first:
          which does it value, and how much price does it give for it?
  claims  up to 3 verified data arguments with a concession on its current package
  step    concessions on its current package until it says final_offer or agreed (or rounds run out)
Then accept the cheapest standing sheet that keeps the must-haves and beats the alternative, or
walk away. In an RFQ, a thread that finishes early asks a short question when it has been idle for
a while, so the arena's 60-second clock does not end it before the others are done.
"""

import json
import logging
import math
import threading
import time

from arena_kit import ArenaError, RemoteTable
from arena_kit.cost import must_haves_ok, total_cost
from arena_kit.docs import standard_terms
from arena_kit.play import ENDED, fetch_documents, latest, moves_left, standing

from .casedata import DOCS, SUPPLIER_SIDE, CaseData

log = logging.getLogger("arena")
OURS = {  # the direction of each lever that helps us
    "payment_days": max,
    "effective_date": max,
    "lead_time_days": min,
    "ppm_commitment": min,
    "chargeback_eur_per_complaint": max,
}
PUSH = 0.985  # after "agreed": ask for this much of the agreed price
IDLE_S = 35.0  # a waiting RFQ thread sends a question after this long (the arena allows 60 s)
KEEPALIVE = "Could you confirm the validity of your offer and your earliest possible delivery date?"


class AutoProbe:
    def __init__(self, client, case_id, package=None, case=None, session_id=None):
        self.client, self.case_id, self.package, self.session_id = client, case_id, package, session_id
        self.table = RemoteTable(client, case)
        self.lock = threading.Lock()
        self.log, self.done = [], {}

    # ---------- levers ----------

    def _ours(self, f, std):
        """Our side of a lever, or None if it has no options."""
        b, opts = self.case["buyer"], [o for o in self.case.get("term_options", {}).get(f, []) if o is not None]
        if f in ("volume_per_year", "contract_months"):  # cover the need over the horizon
            target = b["need_per_year"] if f == "volume_per_year" else round(12 * b["horizon_years"])
            return min(opts, key=lambda o: (abs(o - target), -o)) if opts else None
        if f == "incoterm":
            return min(b["freight_eur_per_unit"], key=b["freight_eur_per_unit"].get)
        return OURS[f](opts) if f in OURS and opts else None

    def _theirs(self, f):
        opts = [o for o in self.case.get("term_options", {}).get(f, []) if o is not None]
        if f == "index_clause":
            return next((o for o in opts if o.get("deadband_pct") == 0), opts[-1] if opts else None)
        if f == "incoterm":
            return "EXW"
        return SUPPLIER_SIDE[f](opts) if f in SUPPLIER_SIDE and opts else None

    def _one_lever_sheets(self, events, price, side):
        """Sheets at `price`, each with one lever moved to `side`; ours: biggest saving first,
        theirs: cheapest for us first. Only levers that change the supplier's current package."""
        _, terms = standing(events)
        std = standard_terms(events)
        base = self.p.sheet({**terms, "unit_price": round(price, 2)}, events)
        c0 = total_cost(self.case, base, std)
        out = []
        for f in self.case["negotiable"]:
            if f == "unit_price":
                continue
            if f == "index_clause" and side == "ours":  # ours: no clause, if it holds one
                if base.get(f) is None:
                    continue
                value = None
            else:
                value = self._ours(f, std) if side == "ours" else self._theirs(f)
                if value is None or value == base.get(f):
                    continue
            sheet = self.p.sheet({**base, f: value}, events)
            if sheet.get(f) != value:
                continue
            out.append((total_cost(self.case, sheet, std) - c0, f, sheet))
        out.sort(key=lambda x: x[0])  # ours: biggest saving first; theirs: cheapest for us first
        return [(f, s) for _, f, s in out[:3]]

    # ---------- one thread ----------

    def _message(self, body, sheets, refs=()):
        return {
            "subject": f"Re: {self.case['title']}"[:300],
            "body": f"Dear Sir or Madam,\n\n{body}\n\nBest regards\nHollerau Pumpenwerke, Purchasing",
            "term_sheets": [{"terms": s} for s in sheets],
            "refs": list(refs),
        }

    def _next(self, sid, events, step):
        """(key, message, note) for this thread's next experiment."""
        _, terms = standing(events)
        price = terms.get("unit_price") or 0
        ours = next(
            (
                m["term_sheets"][0]["terms"]
                for m in reversed(events)
                if m.get("from") == "buyer" and m.get("term_sheets")
            ),
            None,
        )
        anchor = self.p.anchor(sid, events)
        last = (ours or {}).get("unit_price") or anchor
        at = lambda p: self.p.sheet({**terms, "unit_price": round(p, 2)}, events)  # noqa: E731
        if step == "open":
            ask = "Thank you for your offer. Could you send us a cost breakdown for this part? "
            ask = (ask + DOCS.get(self.case["type"], "")).strip() + "\nWhat would you need from us to move on price?"
            return "open", self._message(ask, [at(anchor)]), f"anchor {anchor}"
        if step == "ours":
            sheets = self._one_lever_sheets(events, price, "ours")
            if sheets:
                body = (
                    "We would like to keep your price, with one change in each package below. Which of them can "
                    "you accept?"
                )
                return (
                    "ours",
                    self._message(body, [s for _, s in sheets]),
                    f"at {price}: " + ", ".join(f"{f}={s[f]}" for f, s in sheets),
                )
            step = "theirs"
        if step == "theirs":  # halfway between our anchor and its price: what does each lever buy?
            target = (anchor + price) / 2
            sheets = self._one_lever_sheets(events, target, "theirs")
            if sheets:
                body = "We have put together alternative packages. Which of them works best for you, and at what price?"
                return (
                    "theirs",
                    self._message(body, [s for _, s in sheets]),
                    f"at {target:.2f}: " + ", ".join(f"{f}={s[f]}" for f, s in sheets),
                )
            step = "claims"
        if step == "claims":
            rows = [c for c in self.p.claims if c.get("supplier", sid) == sid][:3]
            if rows:
                body = "We have looked at the figures.\n" + "\n".join(c["text"] for c in rows) + "\nOur offer is below."
                target = last + (price - last) / 3
                refs = [r for c in rows for r in c["refs"]]
                return "claims", self._message(body, [at(target)], refs), "; ".join(c["key"] for c in rows)
        if latest(events).get("status") == "agreed":  # agreed is not the floor: ask for a bit more
            body = "Thank you. Could you do a little better on price? Our proposal is below."
            return "push", self._message(body, [at(price * PUSH)]), f"agreed {price}, ask {price * PUSH:.2f}"
        step_size = max(price * 0.01, (price - last) / 3)
        target = min(last + step_size, price * 0.997)
        return "step", self._message("Thank you. We can move closer, see below.", [at(target)]), f"to {target:.2f}"

    def _held(self, sid):
        """The last push left the agreed price where it was: that is its floor for this package."""
        mine = [e for e in self.log if e.get("supplier_id") == sid]
        return (
            bool(mine)
            and mine[-1]["key"] == "push"
            and mine[-1]["reply"].get("unit_price") == (mine[-2]["reply"].get("unit_price") if len(mine) > 1 else None)
        )

    def _send(self, sid, key, message, note):
        events = self.threads[sid]
        entry = {
            "supplier_id": sid,
            "round": self.case.get("round_limit", 10) - moves_left(self.case, events) + 1,
            "key": key,
            "note": note,
            "sent": [s["terms"] for s in message["term_sheets"]],
            "c_sent": [total_cost(self.case, s["terms"], standard_terms(events)) for s in message["term_sheets"]],
        }
        try:
            reply = self.client.send_message(self.table.session_id, sid, message)
        except ArenaError as e:
            if e.status != 409:
                raise
            reply = self.table.missed(sid, e)
        if "result" in reply:
            return reply
        fetch_documents(self.table, reply)
        _, terms = standing([reply]) if reply.get("term_sheets") else (None, {})
        entry |= {
            "status": reply.get("status"),
            "reply": terms,
            "claims_checked": reply.get("claim_results"),
            "attachments": [a.get("name") for a in reply.get("attachments") or []],
        }
        with self.lock:
            self.threads[sid] = [*events, {**message, "from": "buyer"}, reply]
            self.log.append(entry)
            self.last_reply[sid] = time.monotonic()
        log.info("%s %s %s -> %s %s", sid, key, entry["sent"], entry["status"], terms)
        return reply

    def _thread(self, sid):
        try:
            for step in ["open", "ours", "ours", "theirs", "claims", *["step"] * 10]:
                events = self.threads[sid]
                status = latest(events).get("status")
                if (
                    status in ENDED
                    or status == "final_offer"
                    or moves_left(self.case, events) <= 1
                    or self.over.is_set()
                ):
                    break
                key, message, note = self._next(sid, events, step)
                if key == "push" and self._held(sid):
                    break
                if "result" in self._send(sid, key, message, note):
                    self.over.set()
                    return
            self.done[sid] = True
            while not self.over.is_set() and not all(self.done.get(s) for s in self.threads):
                events = self.threads[sid]
                if latest(events).get("status") in ENDED:
                    return
                if time.monotonic() - self.last_reply[sid] > IDLE_S and moves_left(self.case, events) > 0:
                    self._send(sid, "keepalive", self._message(KEEPALIVE, []), "keep the thread alive")
                time.sleep(1)
        except Exception:
            log.exception("%s failed", sid)
            self.done[sid] = True

    # ---------- the case ----------

    def run(self):
        if self.session_id:  # pick up a session that is already running
            self.case, self.threads = self.table.resume(self.session_id)
        else:
            self.case, self.threads = self.table.open(self.case_id)
        for events in self.threads.values():
            for m in events:
                fetch_documents(self.table, m)
        self.p = CaseData(self.case, self.package)
        self.over = threading.Event()
        self.last_reply = {s: time.monotonic() for s in self.threads}
        workers = [threading.Thread(target=self._thread, args=(s,), daemon=True) for s in self.threads]
        for w in workers:
            w.start()
        for w in workers:
            w.join()
        if self.over.is_set():
            return self.table.result()
        return self._close()

    def _close(self):
        alt = self.case["buyer"].get("alternative") or {}
        c_alt = total_cost(self.case, alt["terms"]) if alt.get("terms", {}).get("unit_price") else math.inf
        best = None
        for sid, events in self.threads.items():
            sheet_id, terms = standing(events)
            if not sheet_id or latest(events).get("status") in ENDED:
                continue
            std = standard_terms(events)
            c = total_cost(self.case, terms, std)
            if must_haves_ok(self.case, terms, std) and c < c_alt and (best is None or c < best[0]):
                best = (c, sid, sheet_id)
        live = [s for s, ev in self.threads.items() if latest(ev).get("status") not in ENDED]
        if best:
            action, sid = {"type": "accept", "term_sheet_id": best[2]}, best[1]
        elif live:
            action, sid = {"type": "walk_away"}, live[0]
        else:
            return self.table.result()
        self.log.append({"key": "close", "action": action, "supplier_id": sid})
        try:
            reply = self.client.send_message(self.table.session_id, sid, {"action": action})
            return reply.get("result", reply)
        except ArenaError:
            return self.table.result()


def summary(result):
    keep = ("deal", "supplier_id", "score", "c_open", "c_deal", "c_alt", "c_best", "terms")
    return json.dumps({k: result.get(k) for k in keep})
