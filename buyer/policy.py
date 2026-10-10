"""The negotiation policy, per supplier thread: plan the non-price terms by C at the supplier's
own valuation, open below its quote, then move toward its counter round by round so it keeps
conceding, with verified claims spread over the rounds. Close on its final offer, its agreement or
the round limit; in relationship goals stop at the price where C is lowest.

What the suppliers showed (sandbox and practice, `docs/learnings.md`):
- they concede only after a move from us and agree as soon as our sheet reaches the counter they
  would make, so our sheet stays below their counter until the end;
- every verified claim they take into account lowers where they stop, most of it in round 1;
- patience runs out at a cumulative gap of about 40 % between our sheets and their counters
  (summed per round, relative to their price), much earlier for a supplier selling near its cost
  or one that is fully booked: a final offer, or a walk-away;
- a large first concession means a deep floor: then we hold low instead of meeting it."""

import base64
import functools
import logging
import time

from arena_kit.docs import standard_terms
from arena_kit.play import latest, moves_left, standing

from . import economics as eco
from . import llm, reader, writer
from .claims import ClaimBank, rival_offer
from .personas import profile, signals_in

log = logging.getLogger("buyer")

FRACTION = 0.3  # share of the gap to the supplier's counter we move per round
# Opening price as a share of its quote at our terms, by category goal. Practice C_best sat 12 to
# 22 % below the quote in leverage, routine and secure-supply cases, 1.5 to 3 % in stabilise ones.
ANCHOR = {"leverage": 0.78, "routine": 0.82, "secure_supply": 0.88, "quality_first": 0.88, "stabilise": 0.92}
ANCHOR_MIN = 0.75  # never open lower than this share (an insult costs patience)
BUDGET = 1.0  # patience: the cumulative relative gap we show (no cap for a typical supplier)
DEEP = 0.06  # a first concession this large (share of its quote) means a deep floor
MIN_MOVE = 0.002  # every sheet moves at least this share of the price
FIRST_CLAIMS, LATER_CLAIMS = 3, 1
DONE = {"agreed", "final_offer"}
ENDED = {"walked_away", "no_bid"}


class Side:
    """One supplier thread: what we know and what we did."""

    def __init__(self, sid):
        self.sid = sid
        self.std = {}
        self.prof = {}
        self.est = {}
        self.terms = {}  # our planned non-price terms (with a price placeholder)
        self.quote = None  # its opening price at our terms
        self.last_sheet = {}  # its previous standing terms
        self.late = 0  # our messages the arena counted as rounds although they came too late
        self.anchor = None
        self.target = None  # relationship goals: the price with the lowest C
        self.budget = BUDGET
        self.claims = []
        self.ours = []  # our prices at s.terms, one per message with a sheet
        self.theirs = []  # its price at our terms, one per reply
        self.gaps = []  # relative gap of each of our sheets to its counter
        self.state = "open"  # open | mirror | closing | done | ended
        self.prev_state = "open"  # the state before the message in flight
        self.pending = None  # the message in flight: what to undo if it times out
        self.tried = set()  # (field, value) we switched away from
        self.term_change = False  # its last counter changed our non-price terms
        self.last_reply = None
        self.asks = []  # what its last e-mail asked of us (reader.asks)
        self.attached = set()  # files we already sent it


class Negotiator:
    def __init__(self, case, pkg=None, complete=None):
        self.case, self.pkg, self.complete = case, pkg, complete
        self.bank = ClaimBank(pkg, case)
        self.sides = {}
        self.used = set()  # claim IDs cited in this case (a rival quote: per supplier)
        self.notes = []  # what we decided, for the log
        self.writer_s = llm.TIMEOUT_S  # wall clock the model may take on the move being built

    # -- setup -------------------------------------------------------------------------------
    def setup(self, sid, events):
        case, s = self.case, Side(sid)
        s.std = safe(lambda: standard_terms(events), {}) or {}
        sheet_id, quote = standing(events)
        s.prof = safe(lambda: profile(self.pkg, sid), profile(None, sid))
        self.read_signals(s, latest(events).get("body"))
        self.sides[sid] = s
        if not sheet_id or quote.get("unit_price") is None:
            s.state = "ended"
            return s
        s.last_sheet = quote
        # a bundle's should-cost is unknown: one component's cost is not the price unit of the kit
        parts = case.get("parts") or []
        full_cost, own_plant = (
            safe(lambda: self.full_cost(parts[0], sid), (None, False)) if len(parts) == 1 else (None, False)
        )
        lead = quote.get("lead_time_days") or s.std.get("lead_time_days")
        overtime = 0.005 if "capacity_full" in s.prof["signals"] else 0.001
        s.est = eco.estimate(
            case, s.std or quote, s.prof["rate"], full_cost, safe(lambda: self.real_ppm(sid)), lead, overtime
        )
        q_price = quote["unit_price"]
        goal, signals = case["buyer"].get("category_goal"), s.prof["signals"]
        sustainable = case["buyer"].get("sustainable_margin_pct") or 0
        if full_cost and goal in eco.RELATIONSHIP_GOALS:
            # it quoted with its margin: a should-cost above that is our estimate's error (P02: 374.95
            # against a quote of 370.96; the relationship charge of the deals says about 368)
            full_cost = min(full_cost, eco.value(case, quote, s.est) * (1 - sustainable / 100))
            s.est["full_cost"] = full_cost
        ratio = ANCHOR.get(goal, 0.85)
        near_cost = bool(own_plant and full_cost >= 0.98 * q_price)  # it sells at our cost estimate
        if goal in eco.RELATIONSHIP_GOALS:
            s.budget = 0.3
        if "price_frozen" in signals:
            ratio = max(ratio, 0.95)  # its list price does not move far; a deep cut only costs patience
        if "capacity_full" in signals:
            ratio, s.budget = max(ratio, 0.93), min(s.budget, 0.16)
        if near_cost:
            ratio, s.budget = max(ratio, 0.97), min(s.budget, 0.14)
        current = case["buyer"].get("current_unit_price")
        if case.get("type") == "price_increase" and current:
            ratio = min(ratio, current / q_price)  # a price increase opens at today's price at most
        ratio = max(ANCHOR_MIN, ratio)
        # terms planned at the price we open with: coverage pays off at a low price, not at the quote
        planned = safe(lambda: eco.plan_terms(case, s.std, s.est, quote, q_price * ratio))
        s.terms = planned[0] if planned else eco.complete_offer(case, eco.at_price(case, quote, q_price * ratio))
        s.anchor = s.terms["unit_price"]
        s.quote = safe(
            lambda: round(eco.price_for_value(case, s.terms, s.est, eco.value(case, quote, s.est)), 2), q_price
        )
        if full_cost and not near_cost:
            s.target = safe(lambda: eco.relationship_optimum(case, s.terms, s.std, s.est, full_cost * 0.85, s.quote))
        safe(lambda: self.trade_clause(s, quote, full_cost))
        s.claims = safe(lambda: self.bank.for_supplier(sid, q_price), [])
        self.note(
            sid,
            "setup",
            quote=quote,
            std=s.std,
            profile=s.prof,
            full_cost=full_cost,
            near_cost=near_cost,
            terms=s.terms,
            quote_at_terms=s.quote,
            anchor=s.anchor,
            target=s.target,
            budget=s.budget,
            claims=[c["text"] for c in s.claims],
        )
        return s

    def trade_clause(self, s, quote, full_cost):
        """An index clause the supplier values more than it costs us (its driver rose over the
        year, the case's path is small): offer it from the start at the price worth the same to it
        as our anchor without it, and in a relationship goal no lower than the relationship
        optimum, where it is agreed at once (P02: Nordmark agreed to a 5 % copper deadband 4 %
        below its fixed price). No trade where its value equals our cost (P08, P18)."""
        case = self.case
        if "index_clause" not in case["negotiable"] or quote.get("index_clause"):
            return
        for clause in case.get("term_options", {}).get("index_clause") or []:
            if clause and clause.get("series") not in s.est["index_moves"]:
                move = self.bank.move12(clause["series"])
                if move is not None:
                    s.est["index_moves"][clause["series"]] = move
        clause = eco.clause_trade(case, s.est)
        if not clause or s.terms.get("index_clause") == clause:
            return
        target_value = eco.value(case, s.terms, s.est)  # our anchor as it is worth to the supplier
        terms = {**s.terms, "index_clause": clause}
        price = eco.price_for_value(case, terms, s.est, target_value)
        floor = None
        if full_cost and case["buyer"].get("category_goal") in eco.RELATIONSHIP_GOALS:
            floor = eco.relationship_optimum(case, terms, s.std, s.est, full_cost * 0.85, s.quote)
            price = max(price, floor or 0.0)
        if not eco.must_haves_ok(case, eco.at_price(case, terms, price), s.std):
            return
        s.terms = eco.at_price(case, terms, price)
        s.anchor = s.terms["unit_price"]
        s.target = floor or s.target
        self.note(s.sid, "clause_trade", clause=clause, anchor=s.anchor, target=s.target)

    def full_cost(self, part, sid):
        """(should-cost of the part, whether it models this supplier's own plant): full cost
        without margin. A generic estimate (a German cost base) says little about one supplier."""
        rows = self.bank.query("SELECT id, supplier_id, unit_cost FROM should_cost WHERE part_id = ?", (part,))
        own = [r for r in rows if r.get("supplier_id") == sid]
        if own:
            return own[0]["unit_cost"], True
        generic = [r for r in rows if not r.get("supplier_id")]
        if generic:
            return generic[0]["unit_cost"], False
        for ref in self.bank.ids("cost:"):  # the case's own facts (no table rows)
            f = self.bank.fact(ref)
            if f and f.get("part") == part and f.get("unit_cost"):
                return f["unit_cost"], f.get("supplier") == sid
        return None, False

    def real_ppm(self, sid):
        """The defect rate it really delivers (latest scorecard), what a chargeback costs it."""
        ids = self.bank.ids(f"sc:{sid.split(':')[-1]}@")
        f = self.bank.fact(ids[-1]) if ids else None
        return f.get("ppm") if f else None

    def restore(self, sid, events):
        """A resumed session (a crash, a restart): rebuild what we sent and what it answered from
        the thread, so the next move continues the path instead of opening at the anchor again."""
        s = self.sides[sid]
        ours = [m for m in events if m.get("from") == "buyer" and m.get("term_sheets")]
        if s.state == "ended" or not ours:
            return
        s.terms = eco.complete_offer(self.case, ours[-1]["term_sheets"][0]["terms"])
        theirs = None
        for m in events:
            if m.get("from") == "buyer":
                self.used.update(m.get("refs") or [])
                if m.get("term_sheets"):
                    price = self.their_price(s, m["term_sheets"][0]["terms"])
                    s.ours.append(price)
                    s.gaps.append(max(0.0, (theirs - price) / theirs) if theirs else 0.0)
            else:
                sheets = m.get("term_sheets") or []
                if sheets and sheets[0].get("terms", {}).get("unit_price") is not None:
                    theirs = self.their_price(s, sheets[0]["terms"])
                    if s.ours:
                        s.theirs.append(theirs)
        if events and events[-1].get("from") != "buyer" and s.theirs:
            s.theirs.pop()  # the latest reply is read by move() like any fresh reply
        self.note(sid, "restore", ours=s.ours, theirs=s.theirs, terms=s.terms)

    # -- reading its reply -------------------------------------------------------------------
    def read_signals(self, s, body):
        """Persona traits in its own e-mail (a supplier the package does not know, or news since):
        merged into the profile; a cash need raises what money now is worth to it."""
        new = [k for k in signals_in(body) if k not in s.prof["signals"]]
        if not new:
            return
        s.prof["signals"] = sorted(s.prof["signals"] + new)
        if "cash_need" in new:
            s.prof["rate"] = round(s.prof["rate"] + 0.05, 3)
            if s.est:
                s.est["interest_rate"] = s.prof["rate"]
        self.note(s.sid, "signals", new=new)

    def their_price(self, s, terms):
        """Its sheet as a price at our planned terms (same value to it)."""
        same = all(terms.get(k) == v for k, v in s.terms.items() if k != "unit_price" and k in terms)
        if same:
            return terms["unit_price"]
        v = eco.value(self.case, terms, s.est)
        return round(eco.price_for_value(self.case, s.terms, s.est, v), 2)

    def switch(self, s, new, why):
        """Plan new non-price terms; our last price moves to the same value for the supplier."""
        if s.ours:
            v = eco.value(self.case, eco.at_price(self.case, s.terms, s.ours[-1]), s.est)
            s.ours[-1] = round(eco.price_for_value(self.case, new, s.est, v), 2)
        if s.theirs:
            v = eco.value(self.case, eco.at_price(self.case, s.terms, s.theirs[-1]), s.est)
            s.theirs[-1] = round(eco.price_for_value(self.case, new, s.est, v), 2)
        s.terms = {**new}
        self.note(s.sid, "switch_terms", why=why, terms={k: v for k, v in new.items() if k != "unit_price"})

    def adopt(self, s, sheets):
        """Its reply changed some of our non-price terms (in its counter or an alternative): it told
        us what it values. Take a sheet's terms over when C at its price beats C of our plan at
        our counterpart of that price; when it insists on an index clause, take the clause that
        costs us least."""
        if not s.ours:
            return
        case = self.case
        standing_terms = sheets[0]["terms"]
        clause = standing_terms.get("index_clause")
        if "index_clause" in s.terms and s.terms["index_clause"] != clause and clause:
            # it will not sell this term at a fixed price (raw-material distributors) and refuses a
            # deadband: take its clause when its sheet, clause included, costs us less than its
            # last one (P08, P18: a longer contract came with it) and keeps every must-have; else
            # keep asking for a fixed price (P02: the copper clause alone cost 1.8 % of spend)
            new = {**s.terms, "index_clause": clause}
            c_now = eco.cost(case, standing_terms, s.std, s.est)
            c_before = eco.cost(case, s.last_sheet, s.std, s.est)
            if eco.must_haves_ok(case, new, s.std) and c_now < c_before - 1.0:
                self.switch(s, new, "its index clause")
            else:
                self.note(s.sid, "keep_terms", why="its index clause costs us more", c_now=c_now, c_before=c_before)
        best_c = eco.cost(case, eco.at_price(case, s.terms, self.their_price(s, standing_terms)), s.std, s.est)
        for sheet in sheets:
            terms = sheet["terms"]
            changed = {k: v for k, v in terms.items() if k != "unit_price" and k in s.terms and s.terms[k] != v}
            changed.pop("index_clause", None)
            if not changed:
                continue
            new = {**s.terms, **changed}
            if not eco.must_haves_ok(case, new, s.std):
                continue
            if any((k, repr(v)) in s.tried for k, v in changed.items()):
                continue  # we were there before: no flip-flop
            c = eco.cost(case, eco.at_price(case, new, terms["unit_price"]), s.std, s.est)
            if c < best_c - max(1.0, 0.001 * best_c):
                best_c = c
                s.tried |= {(k, repr(s.terms.get(k))) for k in changed}
                self.switch(s, new, f"its sheet {changed} costs us less")

    # -- one move ----------------------------------------------------------------------------
    def move(self, sid, threads, writer_s=llm.TIMEOUT_S):
        """The next message to this supplier: {"message": ...}, or None when the thread is done.
        `writer_s`: what the supplier clocks leave for the model paragraph."""
        case, s, events = self.case, self.sides[sid], threads[sid]
        self.writer_s = writer_s
        s.prev_state = s.state
        last = latest(events)
        status = last.get("status")
        if s.state == "ended" or status in ENDED:
            s.state = "ended"
            return None
        sheets = [sh for sh in last.get("term_sheets") or [] if sh.get("terms", {}).get("unit_price") is not None]
        if not sheets:
            s.state = "ended" if not standing(events)[0] else "done"
            return None
        s.std = standard_terms(events) or s.std
        fresh = s.last_reply is not last
        if fresh:
            terms_before = dict(s.terms)
            self.adopt(s, sheets)
            s.term_change = any(sheets[0]["terms"].get(k, v) != v for k, v in terms_before.items() if k != "unit_price")
            s.theirs.append(self.their_price(s, sheets[0]["terms"]))
            s.last_sheet = sheets[0]["terms"]
            s.last_reply = last
            s.asks = reader.asks(last.get("body"))
            self.read_signals(s, last.get("body"))
        theirs = s.theirs[-1]
        if s.state in ("mirror", "closing"):  # we sent its own sheet or our target: done
            s.state = "done"
            return None
        left = self.moves_left(s, events)
        if status in DONE or left <= 0:
            return self.finish(s, sheets, events, theirs, left)
        if s.target and theirs <= s.target * 1.002:
            # relationship goal: below the target a lower price costs more than it saves
            s.state = "closing"
            return self.send(s, [eco.at_price(case, s.terms, max(s.target, theirs))], [], events, theirs)
        if s.ours and theirs <= s.ours[-1]:  # it came below what we offered: take it
            return self.finish(s, sheets, events, theirs, left)
        price, n_claims = self.next_price(s, theirs)
        claims = self.pick(s, n_claims, threads)
        return self.send(s, [eco.at_price(case, s.terms, price)], claims, events, theirs)

    def moves_left(self, s, events):
        """Messages we may still send: the arena counts a late message as a round too."""
        return moves_left(self.case, events) - s.late

    def next_price(self, s, theirs):
        """Our next price at s.terms: open at the anchor; then a share of the gap, held low after a
        large concession, and within the patience budget."""
        if not s.ours:
            return s.anchor, FIRST_CLAIMS
        last = s.ours[-1]
        gap = (theirs - last) / theirs
        conceded = (s.theirs[-2] - theirs) / s.theirs[-2] if len(s.theirs) > 1 else 0.0
        share = FRACTION
        if len(s.ours) == 1 and conceded >= DEEP and not s.term_change:
            # a deep floor: a pure price drop this large means it moves fast on its own (job shops,
            # P05, D02) and agrees at our sheet next: hold the anchor (Dralveck agreed at a held
            # 27.86, at 28.07 after an 8 % step); a drop that came with terms it added (an index
            # clause, P08, P18) is not one
            share = 0.0
        left = max(0.0, s.budget - sum(s.gaps))
        new_gap = min(gap * (1 - share), left / 2)
        if s.budget < 0.2:  # a touchy supplier: small, steady gaps
            new_gap = min(new_gap, 0.015)
        price = theirs * (1 - new_gap)
        price = max(price, last * (1 + MIN_MOVE))
        price = min(price, theirs * 0.998)
        return round(max(price, last), 2), LATER_CLAIMS

    def finish(self, s, sheets, events, theirs, left):
        """Its final word, its agreement or our last message: if one of its alternatives costs us
        less than its standing sheet, send that sheet back so it agrees to it; else done."""
        case = self.case
        std = s.std
        c_stand = eco.cost(case, sheets[0]["terms"], std, s.est)
        alts = [(eco.cost(case, sh["terms"], std, s.est), sh) for sh in sheets[1:]]
        alts = [(c, sh) for c, sh in alts if eco.must_haves_ok(case, sh["terms"], std)]
        if alts and left > 0:
            c, sh = min(alts, key=lambda r: r[0])
            if c < c_stand - 1.0:
                s.state = "mirror"
                terms = {k: v for k, v in sh["terms"].items() if k in case["negotiable"]}
                return self.send(s, [eco.complete_offer(case, terms)], [], events, theirs)
        s.state = "done"
        return None

    def pick(self, s, n, threads):
        """The next unused claims for this supplier: in an RFQ the cheapest rival offer first (a new
        offer is a new argument every round), then its own claims, strongest first."""
        out = []
        rivals = []
        for other, events in threads.items():
            if other == s.sid or latest(events).get("status") in ENDED:
                continue
            oid, t = standing(events)
            if oid and t.get("unit_price") and s.theirs:
                price = self.their_price(s, t)
                if price < s.theirs[-1]:
                    rivals.append((price, rival_offer(other, oid, t["unit_price"])))
        pool = [c for _, c in sorted(rivals, key=lambda r: r[0])[:1]] + s.claims
        for c in pool:
            key = [(s.sid, i) if c.get("rival") else i for i in c["ids"]]
            if any(k in self.used for k in key):
                continue
            out.append(c)
            if len(out) >= n:
                break
        return out

    def facts(self, s, sheets, claims, moved, statements, attachments):
        """Plain statements the model may use, true by construction; its asks come first so the
        paragraph answers them (P11 froze at 45.50 after five unanswered asks for faster payment)."""
        case, out = self.case, []
        fixed = case.get("fixed_terms") or {}
        payment_fixed = "payment_days" not in case["negotiable"] or fixed.get("payment_days")
        if "payment" in s.asks:
            if payment_fixed:
                out.append(
                    "they asked for faster payment: payment terms are fixed in this agreement and cannot change, "
                    "say so plainly and kindly, and point to what we do give (we pay reliably on the due date, "
                    "our full volume, the contract term)"
                )
            else:
                out.append("they asked for faster payment: our proposal below sets the payment term we can offer")
        if "volume" in s.asks or statements:
            out.append(
                "they asked which volume we commit to: the binding volume figure stands right after this paragraph"
            )
        if attachments:
            out.append(
                "they asked for proof of our forecast: the forecast is attached to this e-mail as a file, say so"
            )
        if "volume_per_year" not in case["negotiable"] or fixed.get("volume_per_year"):
            out.append("our order volume is fixed: it is our full demand for this part over the term, all with them")
        if payment_fixed and "payment" not in s.asks:
            out.append("payment terms are fixed for this agreement; we pay reliably on the due date")
        if "contract_months" in case["negotiable"]:
            out.append("we offer a long contract term, which gives them planning security")
        if s.terms.get("index_clause") and self.notes and any(n["what"] == "clause_trade" for n in self.notes):
            out.append(
                "instead of a fixed price we propose an index clause with a deadband on their main cost driver, "
                "so both sides share the material risk; in return the price basis reflects that"
            )
        if any(c["kind"] == "forecast" for c in claims) or any(c["kind"] == "forecast" for c in s.claims):
            out.append("our demand forecast for this part is rising")
        if s.ours and len(s.ours) > 1 and s.ours[-1] > s.ours[-2]:
            out.append("our proposal moves toward them again")
        if moved:
            out.append("they moved in their last reply and we appreciate it")
        if claims:
            out.append("the e-mail cites data right after this paragraph (do not repeat it)")
        out.append("the proposal with all terms follows after the data (do not repeat it)")
        return out

    def statements(self, s, sheets):
        """Code sentences with figures that answer its asks: the binding volume, in round 1 and
        whenever it asks ("Which volume can you commit to?" came 152 times; a figure was "taken
        into account", a description was not)."""
        case = self.case
        if not ("volume" in s.asks or not s.ours):
            return []
        fixed = case.get("fixed_terms") or {}
        sheet = sheets[0]
        volume = sheet.get("volume_per_year") or fixed.get("volume_per_year") or case["buyer"]["need_per_year"]
        months = sheet.get("contract_months") or fixed.get("contract_months")
        term = f"for the {months}-month term" if months else "for this agreement"
        full = " our full demand for this part," if volume >= case["buyer"]["need_per_year"] else ""
        return [f"We confirm a binding volume of {volume} units a year {term},{full} all placed with you."]

    def attachments(self, s):
        """Its proof asked for, as a file it reads: the forecast rows of the part (figures from the
        data, nothing the arena checks as a claim)."""
        if "proof" not in s.asks or "forecast" in s.attached:
            return []
        rows = []
        for part in self.case.get("parts") or []:
            for ref in self.bank.ids(f"fc:{part.split(':')[-1]}@"):
                f = self.bank.fact(ref)
                if f and f.get("volume_per_year") is not None:
                    rows.append((ref.split("@")[-1], part, f["volume_per_year"], f.get("change_pct")))
        if not rows:
            return []
        s.attached.add("forecast")
        lines = ["month,part,volume_per_year,change_pct"] + [",".join(str(x) for x in r) for r in rows]
        content = base64.b64encode("\n".join(lines).encode()).decode()
        return [{"name": "forecast.csv", "type": "csv", "content_b64": content}]

    def send(self, s, sheets, claims, events, theirs):
        first = not s.ours
        moved = len(s.theirs) > 1 and s.theirs[-1] < s.theirs[-2] - 0.005
        price = sheets[0]["unit_price"]
        keys = [(s.sid, i) if c.get("rival") else i for c in claims for i in c["ids"]]
        s.pending = {"state": s.prev_state, "keys": keys}
        statements = self.statements(s, sheets)
        attachments = self.attachments(s)
        if s.state not in ("mirror",):
            s.ours.append(price)
            s.gaps.append(max(0.0, (theirs - price) / theirs) if theirs else 0.0)
            s.pending["appended"] = True
        tone = "warm" if s.prof.get("warm", True) else "friendly and businesslike"
        facts = self.facts(s, sheets, claims, moved, statements, attachments)
        para = llm.paragraph(
            self.complete,
            writer.brief(self.case, s.prof, latest(events).get("body"), facts, tone, first),
            self.writer_s,
        )
        body = writer.email(
            self.case,
            sheets,
            claims,
            statements,
            first=first,
            moved=moved,
            warm=s.prof.get("warm", True),
            paragraph=para,
        )
        refs = sorted({i for c in claims for i in c["ids"]})
        self.note(
            s.sid,
            "send",
            state=s.state,
            theirs=theirs,
            ours=price,
            claims=[c["kind"] for c in claims],
            asks=s.asks,
            attached=[a["name"] for a in attachments],
        )
        message = {
            "subject": reply_subject(events, self.case),
            "body": body,
            "term_sheets": [{"terms": t} for t in sheets],
            "refs": refs,
        }
        if attachments:
            message["attachments"] = attachments
        return {"message": message}

    def fallback_move(self, sid, threads):
        """After an error in move(): our last sheet again with the template e-mail, so the thread
        never falls silent; without a sheet of ours yet, a short question."""
        s = self.sides.get(sid)
        events = threads[sid]
        if not s or not s.ours or not s.terms:
            return {"message": keepalive_message(events)}
        sheets = [eco.at_price(self.case, s.terms, s.ours[-1])]
        body = writer.email(self.case, sheets, [], [], warm=s.prof.get("warm", True))
        self.note(sid, "fallback", ours=s.ours[-1])
        return {
            "message": {
                "subject": reply_subject(events, self.case),
                "body": body,
                "term_sheets": [{"terms": t} for t in sheets],
                "refs": [],
            }
        }

    def commit(self, sid):
        """The message reached the supplier: its claims are spent."""
        s = self.sides[sid]
        if s.pending:
            self.used.update(s.pending["keys"])
            s.pending = None

    def rollback(self, sid):
        """The message came too late (a timeout): the supplier never read it."""
        s = self.sides[sid]
        if s.pending:
            if s.pending.get("appended"):
                s.ours.pop()
                s.gaps.pop()
            s.state = s.pending["state"]
            s.pending = None
            s.late += 1
            self.note(sid, "rollback", late=s.late)

    # -- close -------------------------------------------------------------------------------
    def best_offer(self, threads):
        """(C, supplier, term_sheet_id) of the cheapest acceptable standing sheet (only a standing
        sheet can be accepted; alternatives were sent back to become standing). One supplier's
        broken data skips that supplier, never the close."""
        best = None
        for sid, events in threads.items():
            if latest(events).get("status") in ENDED:
                continue
            oid, terms = standing(events)
            c = safe(functools.partial(self.deal_cost, sid, events, terms)) if oid else None
            if c is not None and (best is None or c < best[0]):
                best = (c, sid, oid)
        return best

    def deal_cost(self, sid, events, terms):
        side = self.sides.get(sid) or Side(sid)
        return eco.deal_cost(self.case, terms, standard_terms(events) or side.std, side.est)

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


def safe(fn, default=None):
    """`fn()`, or `default` when it raises: a hidden case may lack a field the data code expects,
    and a missing claim or profile must never cost the move."""
    try:
        return fn()
    except Exception:  # noqa: BLE001 - logged, the move goes on with the default
        log.exception("skipped: %s", getattr(fn, "__name__", fn))
        return default


def reply_subject(events, case):
    subject = latest(events).get("subject") or f"Re: {case['title']}"
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"
    return subject[:300]


def keepalive_message(events):
    subject = latest(events).get("subject") or "Re: your offer"
    return {"subject": subject[:300], "body": writer.keepalive(), "term_sheets": []}


def deadline_near(deadline, margin=90):
    cap = deadline() if callable(deadline) else deadline
    return bool(cap) and time.time() > cap - margin
