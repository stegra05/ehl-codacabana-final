"""The negotiation policy, per supplier thread: plan the non-price terms by C at the supplier's
own valuation, open below its quote, then move a share of the gap to its counter each round so
it keeps conceding, with verified claims spread over the rounds. Close on its final offer, its
agreement or the round limit; in relationship goals stop at the price where C is lowest.

Evidence (sandbox D01, `docs/learnings.md`): suppliers concede only after a move from us, agree as
soon as our sheet reaches the counter they would make, and every verified claim they take into
account lowers where they stop."""

import logging
import threading
import time

from arena_kit.docs import standard_terms
from arena_kit.play import latest, moves_left, standing

from . import economics as eco
from . import writer
from .claims import ClaimBank, rival_offer
from .personas import profile

log = logging.getLogger("buyer")

FRACTION = 0.3  # share of the gap to the supplier's counter we move per round
# Opening price as a share of its quote at our terms, by category goal. Practice C_best sat 12 to
# 22 % below the quote in leverage, routine and secure-supply cases, 1.5 to 3 % in stabilise ones.
ANCHOR = {"leverage": 0.78, "routine": 0.8, "secure_supply": 0.85, "quality_first": 0.88, "stabilise": 0.92}
ANCHOR_MIN = 0.75  # never open lower than this share (an insult costs patience)
FIRST_CLAIMS, LATER_CLAIMS = 3, 1
DONE = {"agreed", "final_offer"}
ENDED = {"walked_away", "no_bid"}
QUESTION = "Could you share your cost breakdown for this part, so we understand the drivers together?"


class Side:
    """One supplier thread: what we know and what we did."""

    def __init__(self, sid):
        self.sid = sid
        self.std = {}
        self.prof = {}
        self.est = {}
        self.terms = {}  # our planned non-price terms (with a price placeholder)
        self.quote = None  # its opening price at our terms
        self.target = None  # relationship goals: the price with the lowest C
        self.claims = []
        self.ours = []  # our prices, one per message with a sheet
        self.theirs = []  # its price at our terms, one per reply
        self.state = "open"  # open | done | ended
        self.last_reply = None


class Negotiator:
    def __init__(self, case, pkg=None):
        self.case, self.pkg = case, pkg
        self.bank = ClaimBank(pkg, case)
        self.sides = {}
        self.used = set()  # claim IDs cited in this case (a rival quote: per supplier)
        self.lock = threading.Lock()
        self.notes = []  # what we decided, for the log

    # -- setup -------------------------------------------------------------------------------
    def setup(self, sid, events):
        case, s = self.case, Side(sid)
        s.std = standard_terms(events) or {}
        sheet_id, quote = standing(events)
        s.prof = profile(self.pkg, sid)
        if not sheet_id or quote.get("unit_price") is None:
            s.state = "ended"
            self.sides[sid] = s
            return s
        part = (case.get("parts") or [None])[0]
        full_cost = self.full_cost(part, sid)
        s.est = eco.estimate(case, s.std or quote, s.prof["rate"], full_cost, self.real_ppm(sid))
        q_price = quote["unit_price"]
        ratio = ANCHOR.get(case["buyer"].get("category_goal"), 0.85)
        if "price_frozen" in s.prof["signals"]:
            ratio = max(ratio, 0.95)  # its list price does not move far; a deep cut only costs patience
        current = case["buyer"].get("current_unit_price")
        if case.get("type") == "price_increase" and current:
            ratio = min(ratio, current / q_price)  # a price increase opens at today's price at most
        ratio = max(ANCHOR_MIN, ratio)
        # terms planned at the price we open with: coverage pays off at a low price, not at the quote
        planned = eco.plan_terms(case, s.std, s.est, quote, q_price * ratio)
        s.terms = planned[0] if planned else eco.at_price(case, quote, q_price * ratio)
        s.anchor = s.terms["unit_price"]
        s.quote = round(eco.price_for_value(case, s.terms, s.est, eco.value(case, quote, s.est)), 2)
        if full_cost:
            s.target = eco.relationship_optimum(case, s.terms, s.std, s.est, full_cost * 0.85, s.quote)
        s.claims = self.bank.for_supplier(sid, quote["unit_price"])
        self.sides[sid] = s
        self.note(
            sid,
            "setup",
            quote=quote,
            std=s.std,
            profile=s.prof,
            full_cost=full_cost,
            terms=s.terms,
            quote_at_terms=s.quote,
            anchor=s.anchor,
            target=s.target,
            claims=[c["text"] for c in s.claims],
        )
        return s

    def full_cost(self, part, sid):
        """The should-cost of the part (this supplier's plant first): full cost without margin."""
        best = None
        for ref in self.bank.ids("cost:"):
            f = self.bank.fact(ref)
            if f and f.get("part") == part and f.get("unit_cost"):
                if ref.endswith("-" + sid.split(":")[-1]):
                    return f["unit_cost"]
                if "-" not in ref.split(":")[-1]:
                    best = f["unit_cost"]
        return best

    def real_ppm(self, sid):
        """The defect rate it really delivers (latest scorecard), what a chargeback costs it."""
        ids = self.bank.ids(f"sc:{sid.split(':')[-1]}@")
        f = self.bank.fact(ids[-1]) if ids else None
        return f.get("ppm") if f else None

    def adopt(self, s, terms):
        """Its counter changed some of our non-price terms: take them over when they cost us little
        (it answered what it values), keep ours when they would cost us more than 0.5 %."""
        changed = {
            k: v for k, v in terms.items() if k != "unit_price" and k in s.terms and s.terms[k] != v and v is not None
        }
        if not changed or not s.ours:
            return
        new = {**s.terms, **changed}
        if not eco.must_haves_ok(self.case, new, s.std):
            return
        v = eco.value(self.case, eco.at_price(self.case, s.terms, s.ours[-1]), s.est)
        ours_new = eco.price_for_value(self.case, new, s.est, v)
        c_old = eco.cost(self.case, eco.at_price(self.case, s.terms, s.ours[-1]), s.std, s.est)
        c_new = eco.cost(self.case, eco.at_price(self.case, new, ours_new), s.std, s.est)
        if c_new > c_old * 1.005:
            self.note(s.sid, "keep_terms", theirs=changed)
            return
        s.terms = new
        s.ours[-1] = round(ours_new, 2)
        self.note(s.sid, "adopt_terms", changed=changed, ours=s.ours[-1])

    # -- one move ----------------------------------------------------------------------------
    def their_price(self, s, terms):
        """Its sheet as a price at our planned terms (same value to it)."""
        same = all(terms.get(k) == v for k, v in s.terms.items() if k != "unit_price" and k in terms)
        if same:
            return terms["unit_price"]
        v = eco.value(self.case, terms, s.est)
        return round(eco.price_for_value(self.case, s.terms, s.est, v), 2)

    def move(self, sid, threads):
        """The next message to this supplier: {"message": ...}, or None when the thread is done."""
        case, s, events = self.case, self.sides[sid], threads[sid]
        last = latest(events)
        status = last.get("status")
        if s.state == "ended" or status in ENDED:
            s.state = "ended"
            return None
        sheet_id, terms = standing(events)
        if not sheet_id or terms.get("unit_price") is None:
            s.state = "ended"
            return None
        s.std = standard_terms(events) or s.std
        if s.last_reply is not last:
            self.adopt(s, terms)
        theirs = self.their_price(s, terms)
        if not s.theirs or s.last_reply is not last:
            s.theirs.append(theirs)
            s.last_reply = last
        if status in DONE or moves_left(case, events) <= 0:
            s.state = "done"
            return None
        if s.state == "closing":  # we offered the target price; whatever it answered, we are done
            s.state = "done"
            return None
        if s.target and theirs <= s.target * 1.002:
            # relationship goal: below the target a lower price costs more than it saves
            s.state = "closing"
            return self.send(s, [eco.at_price(case, s.terms, max(s.target, theirs))], [], events, theirs)
        if s.ours and theirs <= s.ours[-1]:  # it came below what we offered: take it
            s.state = "done"
            return None
        if not s.ours:
            price = s.anchor
            n_claims, question = FIRST_CLAIMS, QUESTION
        else:
            price = s.ours[-1] + FRACTION * (theirs - s.ours[-1])
            n_claims, question = LATER_CLAIMS, None
        price = min(price, theirs * 0.998)
        price = round(max(price, s.ours[-1] if s.ours else 0.0), 2)
        claims = self.pick(s, n_claims, threads)
        return self.send(s, [eco.at_price(case, s.terms, price)], claims, events, theirs, question)

    def pick(self, s, n, threads):
        """The next unused claims for this supplier, rival offers in an RFQ first."""
        out = []
        with self.lock:
            rivals = []
            for other, events in threads.items():
                if other == s.sid or latest(events).get("status") in ENDED:
                    continue
                oid, t = standing(events)
                if oid and t.get("unit_price") and s.theirs and self.their_price(s, t) < s.theirs[-1]:
                    rivals.append(rival_offer(other, oid, t["unit_price"]))
            pool = sorted(rivals, key=lambda c: c["text"])[:1] + s.claims
            for c in pool:
                key = [(s.sid, i) if c.get("rival") else i for i in c["ids"]]
                if any(k in self.used for k in key):
                    continue
                out.append(c)
                self.used.update(key)
                if len(out) >= n:
                    break
        return out

    def send(self, s, sheets, claims, events, theirs, question=None):
        first = not s.ours
        moved = len(s.theirs) > 1 and s.theirs[-1] < s.theirs[-2] - 0.005
        s.ours.append(sheets[0]["unit_price"])
        body = writer.email(
            self.case, sheets, claims, question, first=first, moved=moved, warm=s.prof.get("warm", True)
        )
        refs = sorted({i for c in claims for i in c["ids"]})
        self.note(s.sid, "send", theirs=theirs, ours=sheets[0]["unit_price"], claims=[c["kind"] for c in claims])
        subject = latest(events).get("subject") or f"Re: {self.case['title']}"
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"
        return {
            "message": {
                "subject": subject[:300],
                "body": body,
                "term_sheets": [{"terms": t} for t in sheets],
                "refs": refs,
            }
        }

    # -- close -------------------------------------------------------------------------------
    def best_offer(self, threads):
        """(C, supplier, term_sheet_id) of the cheapest acceptable standing sheet, alternatives included."""
        best = None
        for sid, events in threads.items():
            last = latest(events)
            if last.get("status") in ENDED:
                continue
            std = standard_terms(events) or self.sides.get(sid, Side(sid)).std
            for sheet in last.get("term_sheets") or []:
                terms, oid = sheet.get("terms") or {}, sheet.get("term_sheet_id")
                if oid and eco.acceptable(self.case, terms, std):
                    c = eco.cost(self.case, terms, std, self.sides[sid].est if sid in self.sides else None)
                    if best is None or c < best[0]:
                        best = (c, sid, oid)
        return best

    def close(self, threads):
        best = self.best_offer(threads)
        if best is None:
            live = [sid for sid, ev in threads.items() if latest(ev).get("status") not in ENDED] or list(threads)
            self.note(None, "walk_away")
            return {"supplier_id": live[0], "message": {"action": {"type": "walk_away"}}}
        self.note(best[1], "accept", c=best[0], offer=best[2])
        return {"supplier_id": best[1], "message": {"action": {"type": "accept", "term_sheet_id": best[2]}}}

    def note(self, sid, what, **kw):
        entry = {"t": round(time.time(), 1), "supplier": sid, "what": what, **kw}
        self.notes.append(entry)
        log.info(
            "%s %s %s",
            self.case["case_id"],
            sid,
            {k: v for k, v in entry.items() if k not in ("claims", "std", "profile")},
        )


def keepalive_message(events):
    subject = latest(events).get("subject") or "Re: your offer"
    return {"subject": subject[:300], "body": writer.keepalive(), "term_sheets": []}


def done(threads):
    return all(latest(ev).get("status") in ENDED | DONE for ev in threads.values())


def deadline_near(deadline, margin=90):
    cap = deadline() if callable(deadline) else deadline
    return bool(cap) and time.time() > cap - margin

