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
import json
import logging
import re
import time

from arena_kit.docs import standard_terms
from arena_kit.play import ENDED, latest, live_threads, moves_left, standing

from . import analyst, llm, writer
from . import economics as eco
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
HOLD = 0.7  # the live analyst's "hold": it still concedes, we move this share of our usual step
ANALYST_MIN_S = 10.0  # the clocks must leave this much for analyst and writer together, else no analyst
TRADE_MIN = 0.7  # a trade sheet's price never sits below this share of what the supplier quotes for it
DONE = {"agreed", "final_offer"}

# What the supplier's e-mail asks of us
ASKS = {
    # a binding volume figure; stated in words with the figure, it was "taken into account" (D01, D02)
    "volume": r"volume (can )?you (can )?commit|binding (higher )?volume|higher (order )?volume|volume figures"
    r"|confirm .{0,40}volume|anticipated (order )?volume",
    # proof of the forecast or of figures we mentioned without an ID
    "proof": r"proof of|send us the data|figures is that based|provide the (volume|forecast|binding)"
    r"|forecast data|volume data",
    # it wants to be paid sooner
    "payment": r"faster payment|pay(ment)? (terms )?(earlier|faster|sooner|within)|need .{0,12}days payment"
    r"|shorter payment|quicker payment|cash flow",
    # it asks for our current price level or our target
    "target": r"what price|which price|your target|price you have in mind",
}


def asks(body):
    """The kinds of ask in a supplier e-mail, in a fixed order. The bots write their asks in a few
    fixed sentences ("Which volume can you commit to?", "Please send us the data."), so plain
    patterns read them; no model, no latency."""
    text = body or ""
    return [k for k, pat in ASKS.items() if re.search(pat, text, re.I)]


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
        self.state = "open"  # open | mirror | done | ended
        self.prev_state = "open"  # the state before the message in flight
        self.pending = None  # the message in flight: what to undo if it times out
        self.last_sent_terms = None  # last committed primary sheet, for the no-progress guard
        self.used_claim_families = set()  # semantic evidence already used with this supplier
        self.offered_trade_keys = set()  # term/value alternatives already offered in this thread
        self.term_change = False  # its last counter changed our non-price terms
        self.last_reply = None
        self.asks = []  # what its last e-mail asked of us (asks)
        self.attached = set()  # files we already sent it
        self.research = ""  # the lead researcher's notes for the e-mail writer
        self.trades = []  # terms the lead expects it to value: offered next to our opening sheet
        self.active_trades = []  # explicit supplier needs priced for the current move
        self.playbook = {}  # the demo bidding: its expected arguments, our answers, points to press
        self.live = ""  # the live analyst's notes on its last e-mail
        self.mood = None  # the live analyst on its last e-mail: the writer's mood
        self.tactic = None  # and our next move: steady | hold | argue
        self.tactics = []  # every tactic played, for the debrief
        self.argument = 0  # which expected argument its last e-mail made (1-based), 0 for none


class Negotiator:
    def __init__(self, case, pkg=None, complete=None, briefs=None):
        """`briefs`: the research team's brief per supplier (`research.briefs`); None plays the
        plain price engine, without the research strategy and without the live analyst."""
        self.case, self.pkg, self.complete, self.briefs = case, pkg, complete, briefs
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
        brief = (self.briefs or {}).get(sid) or {}
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
        if brief:
            self.apply(s, brief)
        # terms planned at the price we open with: coverage pays off at a low price, not at the quote
        planned = safe(lambda: eco.plan_terms(case, s.std, s.est, quote, q_price * ratio))
        s.terms = planned[0] if planned else eco.complete_offer(case, eco.at_price(quote, q_price * ratio))
        s.anchor = s.terms["unit_price"]
        s.quote = safe(
            lambda: round(eco.price_for_value(case, s.terms, s.est, eco.value(case, quote, s.est)), 2), q_price
        )
        if full_cost:
            # also for a supplier selling at our cost estimate: below the optimum a lower price costs
            # us more than it saves, and pushing on made Nordmark withdraw (P02 v1)
            s.target = safe(lambda: eco.relationship_optimum(case, s.terms, s.std, s.est, full_cost * 0.85, s.quote))
        safe(lambda: self.trade_clause(s, quote, full_cost))
        s.claims = safe(lambda: self.bank.for_supplier(sid, q_price), [])
        order = brief.get("claim_order") or []  # the arguments the lead expects this supplier to accept, first
        s.claims.sort(key=lambda c: order.index(c["kind"]) if c["kind"] in order else len(order))
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

    def apply(self, s, brief):
        """The research team's brief on this thread: the lead's trades wait for our opening sheet,
        the demo bidding's playbook for the supplier's arguments; notes and tone go to the e-mail
        writer. Prices and pace stay with the policy: a model moving them cost score (D01, D02,
        P04, `docs/learnings.md`)."""
        s.research = brief.get("notes") or ""
        s.trades = brief.get("trades") or []
        s.playbook = brief.get("playbook") or {}
        if brief.get("tone"):
            s.prof["warm"] = brief["tone"] == "warm"
        self.note(
            s.sid,
            "research",
            trades=s.trades,
            reason=brief.get("reason"),
            playbook=s.playbook,
            findings=brief.get("findings"),
        )

    def trade_sheets(self, s, main):
        """The lead's trades as extra sheets next to our opening sheet `main`: each changes one
        term and carries the price at which it costs us exactly what `main` costs, so whichever
        the supplier picks, we lose nothing and learn what it values. A trade whose price would
        sit at or above what the supplier quotes for those terms, or far below it, is not offered."""
        case, out = self.case, []
        c_main = eco.cost(case, main, s.std, s.est)
        for trade in s.trades:
            terms = {**main, trade["field"]: trade["value"]}
            if terms == main or not eco.must_haves_ok(case, terms, s.std):
                continue
            lo, hi = 0.0, main["unit_price"] * 3
            if (
                not eco.cost(case, eco.at_price(terms, lo), s.std, s.est)
                < c_main
                < eco.cost(case, eco.at_price(terms, hi), s.std, s.est)
            ):
                continue
            for _ in range(50):  # C rises with the price
                mid = (lo + hi) / 2
                lo, hi = (mid, hi) if eco.cost(case, eco.at_price(terms, mid), s.std, s.est) < c_main else (lo, mid)
            sheet = eco.at_price(terms, int(lo * 100) / 100)
            quoted = eco.price_for_value(case, terms, s.est, eco.value(case, eco.at_price(s.terms, s.quote), s.est))
            if not TRADE_MIN * quoted <= sheet["unit_price"] < 0.995 * quoted:
                continue
            out.append(sheet)
            self.note(s.sid, "trade_sheet", trade=trade, price=sheet["unit_price"], quoted=round(quoted, 2))
        return out

    def trade_clause(self, s, quote, full_cost):
        """An index clause the supplier values more than it costs us (its driver rose over the
        year, the case's path is small): offer it from the start at the price worth the same to it
        as our anchor without it, and in a relationship goal no lower than the relationship
        optimum, where it is agreed at once (P02: Nordmark agreed to a 5 % copper deadband 4 %
        below its fixed price). No trade where its value equals our cost (P08, P18)."""
        case = self.case
        if "index_clause" not in case["negotiable"] or quote.get("index_clause"):
            return
        if "hedged" in s.prof["signals"]:
            return  # its material is bought forward at fixed prices: the index does not reach its costs
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
        if not eco.must_haves_ok(case, eco.at_price(terms, price), s.std):
            return
        s.terms = eco.at_price(terms, price)
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
                refs = m.get("refs") or []
                self.used.update(refs)
                s.used_claim_families.update(
                    family for ref in refs for family in self.claim_families({"kind": "forecast", "ids": [ref]})
                )
                if m.get("term_sheets"):
                    sent_sheets = [sh.get("terms") or {} for sh in m["term_sheets"]]
                    s.last_sent_terms = dict(sent_sheets[0])
                    s.offered_trade_keys.update(self.trade_keys(sent_sheets))
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

    def bound_full_cost(self, s, terms):
        """A supplier does not offer below its cost floor (`docs/api.md`, What counts): every sheet
        it sends, valued to it (its clause included), bounds our full-cost estimate from above. The
        should-cost overshot the true full cost by 1 to 2 % on P01, P02 and P03 (the relationship
        charge of 32 practice deals), and the relationship target built on it closed above the
        supplier's own counter (P01: 131.27 in 8 sessions, 0.909, against 130.08, 0.978)."""
        full_cost = s.est.get("full_cost")
        if not full_cost:
            return
        offered = eco.value(self.case, terms, s.est)
        if offered < full_cost:
            s.est["full_cost"] = offered
            self.note(s.sid, "full_cost_bound", offered=round(offered, 2), was=round(full_cost, 2))

    def listen(self, s, body):
        """The live analyst on its latest e-mail: the mood goes to the writer, the tactic paces our
        next price and our evidence, the argument it recognised picks our prepared answer, its
        asks join what the patterns found. Its time comes out of the writer's; late or off, the
        move goes on with the patterns alone."""
        s.mood, s.tactic, s.argument = None, None, 0
        if self.writer_s < ANALYST_MIN_S:  # several threads share the clocks: the move comes first
            return
        t0 = time.monotonic()
        arguments = s.playbook.get("arguments") or []
        seen = analyst.read(self.complete, self.case, body, s.ours, s.theirs, arguments, self.writer_s / 2)
        self.writer_s -= time.monotonic() - t0
        if seen is None:
            return
        s.asks = [k for k in ASKS if k in s.asks or k in seen["asks"]]
        s.mood, s.tactic, s.argument, s.live = seen["mood"], seen["tactic"], seen["argument"], seen["notes"]
        s.tactics.append(s.tactic)
        self.note(s.sid, "analyst", seconds=round(time.monotonic() - t0, 1), **seen)

    def team_facts(self, s, first, extra):
        """What the team adds to the writer's facts: our prepared answer to the argument its e-mail
        made, a weak point to press in the opening, the trades on offer, the mood to meet."""
        out = []
        rebuttals = s.playbook.get("rebuttals") or []
        if s.argument and s.argument <= len(rebuttals) and rebuttals[s.argument - 1]:
            out.append(
                f'they argue: "{s.playbook["arguments"][s.argument - 1]}" Our answer, in your own words: '
                f"{rebuttals[s.argument - 1]}"
            )
        if first and s.playbook.get("press"):
            out.append(f"a point to raise politely, once: {s.playbook['press'][0]}")
        if extra:
            why = "; ".join(t["why"] for t in [*s.trades, *s.active_trades] if t.get("why"))
            out.append(
                "our proposal lists alternative packages after the first one: say they are free to choose the "
                f"one that suits them best ({why})"
            )
        elif s.active_trades:
            why = "; ".join(t["why"] for t in s.active_trades if t.get("why"))
            out.append(f"we adjusted the package in response to {why}; explain the commercial terms clearly")
        if s.mood == "irritated":
            out.append("they sound irritated: acknowledge it sincerely before anything else")
        elif s.mood == "pressured":
            out.append("they sound under pressure: be calm and make the next step easy for them")
        return out

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
            v = eco.value(self.case, eco.at_price(s.terms, s.ours[-1]), s.est)
            s.ours[-1] = round(eco.price_for_value(self.case, new, s.est, v), 2)
        if s.theirs:
            v = eco.value(self.case, eco.at_price(s.terms, s.theirs[-1]), s.est)
            s.theirs[-1] = round(eco.price_for_value(self.case, new, s.est, v), 2)
        s.terms = {**new}
        self.note(s.sid, "switch_terms", why=why, terms={k: v for k, v in new.items() if k != "unit_price"})

    def adopt(self, s, sheets):
        """Compare complete quoted packages, then switch once to the cheapest useful one."""
        if not s.ours:
            return
        case = self.case
        standing = sheets[0]["terms"]
        planned_cost = eco.cost(case, eco.at_price(s.terms, self.their_price(s, standing)), s.std, s.est)
        candidates = []
        for sheet in sheets:
            new = eco.quoted_offer(case, sheet["terms"], s.std)
            if new is None or all(new.get(k) == v for k, v in s.terms.items() if k != "unit_price"):
                continue
            c = eco.deal_cost(case, new, s.std, s.est)
            if c is not None and c < planned_cost - max(1.0, 0.001 * planned_cost):
                candidates.append((c, new))
        if candidates:
            _, new = min(candidates, key=lambda row: (row[0], repr(sorted(row[1].items()))))
            self.switch(s, new, "complete quoted package costs us less")

    # -- one move ----------------------------------------------------------------------------
    def move(self, sid, threads, writer_s=llm.TIMEOUT_S):
        """The next message to this supplier: {"message": ...}, or None when the thread is done.
        `writer_s`: what the supplier clocks leave for the model paragraph."""
        s, events = self.sides[sid], threads[sid]
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
        std_before = s.std
        s.std = standard_terms(events) or s.std
        fresh = s.last_reply is not last
        if fresh:
            terms_before = dict(s.terms)
            estimate_before = dict(s.est)
            self.adopt(s, sheets)
            s.term_change = any(sheets[0]["terms"].get(k, v) != v for k, v in terms_before.items() if k != "unit_price")
            s.theirs.append(self.their_price(s, sheets[0]["terms"]))
            self.bound_full_cost(s, sheets[0]["terms"])
            s.last_sheet = sheets[0]["terms"]
            s.last_reply = last
            s.asks = asks(last.get("body"))
            self.read_signals(s, last.get("body"))
            if self.briefs is not None and status not in DONE:
                self.listen(s, last.get("body"))
            economics_changed = s.terms != terms_before or s.est != estimate_before or s.std != std_before
            if s.target is not None and economics_changed:
                s.target = eco.relationship_optimum(
                    self.case,
                    s.terms,
                    s.std,
                    s.est,
                    s.est["full_cost"] * 0.85,
                    max(s.est["full_cost"] * 0.85, s.quote, s.target, s.theirs[-1]),
                )
        theirs = s.theirs[-1]
        if s.state == "mirror":  # we sent its own sheet: done
            s.state = "done"
            return None
        left = self.moves_left(s, events)
        if status in DONE or left <= 0:
            return self.finish(s, sheets, events, theirs, left)
        cap = eco.break_even(self.case, s.terms, s.std, s.est)
        if s.ours and s.target and theirs <= s.target:
            # The supplier already offers at or below our estimated optimum. Let the close gate
            # evaluate its standing sheet instead of raising the price to our target.
            s.state = "done"
            return None
        if s.ours and theirs <= s.ours[-1]:  # it came below what we offered: take it
            return self.finish(s, sheets, events, theirs, left)
        price, n_claims = self.next_price(s, theirs)
        if cap is not None and price > cap:
            price = max(cap, s.ours[-1]) if s.ours else cap  # never above the alternative, never back down
            self.note(sid, "break_even_cap", cap=cap, price=price)
        claims = self.pick(s, n_claims, threads)
        sheets = [eco.at_price(s.terms, price)]
        if not s.ours and s.trades:
            sheets += safe(lambda: self.trade_sheets(s, sheets[0]), [])[:2]
        elif s.ours:
            sheets += safe(lambda: self.need_trade_sheets(s, sheets[0]), [])[:2]
        switched_trade_keys = set()
        if self.same_offer(s.last_sent_terms, sheets[0]):
            if len(sheets) == 1:
                s.state = "done"
                self.note(sid, "no_progress", reason="unchanged price and terms")
                return None
            # Do not resend the old primary sheet. Move the thread onto the best new package,
            # whose buyer cost is lower and whose estimated supplier value matches the main offer.
            switched_trade_keys = self.trade_keys(sheets)
            sheet = sheets[1]
            old_target = s.target
            self.switch(s, sheet, "cost-checked response to a supplier need")
            if old_target is not None and s.est.get("full_cost"):
                floor = s.est["full_cost"] * 0.85
                s.target = eco.relationship_optimum(
                    self.case,
                    s.terms,
                    s.std,
                    s.est,
                    floor,
                    max(floor, s.quote, old_target, s.theirs[-1]),
                )
            sheets = [sheet]
        result = self.send(s, sheets, claims, events, theirs)
        if s.pending and switched_trade_keys:
            s.pending["trade_keys"].update(switched_trade_keys)
        return result

    def moves_left(self, s, events):
        """Messages we may still send: the arena counts a late message as a round too."""
        return moves_left(self.case, events) - s.late

    def next_price(self, s, theirs):
        """Our next price at s.terms: open at the anchor; then a share of the gap, held low after a
        large concession, and within the patience budget."""
        if not s.ours:
            return s.anchor, FIRST_CLAIMS
        last = s.ours[-1]
        conceded = (s.theirs[-2] - theirs) / s.theirs[-2] if len(s.theirs) > 1 else 0.0
        fraction = FRACTION * (HOLD if s.tactic == "hold" else 1.0)
        price = step(last, theirs, conceded, len(s.ours) == 1, fraction, s.budget, sum(s.gaps), s.term_change)
        return round(max(price, last), 2), LATER_CLAIMS + (s.tactic == "argue")  # an argument gets evidence

    def finish(self, s, sheets, events, theirs, left):
        """Its final word, its agreement or our last message: if one of its alternatives costs us
        less than its standing sheet, send that sheet back so it agrees to it; else done."""
        case = self.case
        std = s.std
        c_stand = eco.deal_cost(case, sheets[0]["terms"], std, s.est)
        alts = []
        for sh in sheets[1:]:
            terms = eco.quoted_offer(case, sh["terms"], std)
            c = eco.deal_cost(case, terms, std, s.est) if terms is not None else None
            if c is not None:
                alts.append((c, terms))
        if alts and left > 0:
            c, terms = min(alts, key=lambda row: row[0])
            if c_stand is None or c < c_stand - 1.0:
                s.state = "mirror"
                return self.send(s, [terms], [], events, theirs)
        if c_stand is None and left > 0 and s.ours:
            # its last word is a deal we would refuse (dearer than our alternative, or a must-have
            # broken): one sheet at the most we would accept costs nothing, since a refusal here
            # and a walk-away both leave us the alternative
            cap = eco.break_even(case, s.terms, std, s.est)
            last = eco.at_price(s.terms, min(theirs, cap) if cap is not None else theirs)
            if eco.deal_cost(case, last, std, s.est) is not None and not self.same_offer(s.last_sent_terms, last):
                s.state = "mirror"
                self.note(s.sid, "last_sheet", price=last["unit_price"], theirs=theirs, cap=cap)
                return self.send(s, [last], [], events, theirs)
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
        selected_families = set()
        for c in pool:
            key = [(s.sid, i) if c.get("rival") else i for i in c["ids"]]
            if any(k in self.used for k in key):
                continue
            families = self.claim_families(c)
            if families & (s.used_claim_families | selected_families):
                continue
            out.append(c)
            selected_families.update(families)
            if len(out) >= n:
                break
        return out

    @staticmethod
    def claim_families(claim):
        """Forecast rows for the same period make one demand-growth argument."""
        if claim.get("kind") != "forecast" or claim.get("rival"):
            return set()
        periods = {month for ref in claim.get("ids", []) for month in re.findall(r"@(\d{4}-\d{2})", ref)}
        return {("forecast", month) for month in periods}

    @staticmethod
    def same_offer(previous, candidate):
        if not previous or not candidate:
            return False
        previous_terms = {k: v for k, v in previous.items() if k != "unit_price"}
        candidate_terms = {k: v for k, v in candidate.items() if k != "unit_price"}
        if previous_terms != candidate_terms:
            return False
        try:
            return abs(float(previous.get("unit_price")) - float(candidate.get("unit_price"))) <= 0.005
        except (TypeError, ValueError):
            return False

    @staticmethod
    def trade_key(field, value):
        return json.dumps([field, value], sort_keys=True, separators=(",", ":"))

    def trade_keys(self, sheets):
        """Remember one-term alternatives already shown, including after a resumed session."""
        if len(sheets) < 2:
            return set()
        main = sheets[0]
        out = set()
        for sheet in sheets[1:]:
            changed = [f for f in self.case.get("negotiable", []) if f != "unit_price" and sheet.get(f) != main.get(f)]
            if len(changed) == 1:
                field = changed[0]
                out.add(self.trade_key(field, sheet[field]))
        return out

    def need_trade_sheets(self, s, main):
        """Offer evidence-backed supplier needs only when their complete package costs us less.

        The price preserves our estimated supplier value; must-haves, allowed values, the alternative
        and full buyer cost remain hard gates. Unknown volume/capacity value is never invented.
        """
        signals = set(s.prof.get("signals") or [])
        requested = set()
        if "payment" in s.asks or "cash_need" in signals:
            requested.add(("payment_days", "lower"))
        if "volume" in s.asks or "spare_capacity" in signals:
            requested.add(("volume_per_year", "higher"))
        if "capacity_full" in signals:
            requested.update({("lead_time_days", "higher"), ("contract_months", "higher")})
        if not requested:
            s.active_trades = []
            return []

        case = self.case
        base_cost = eco.cost(case, main, s.std, s.est)
        base_value = eco.value(case, main, s.est)
        found = []
        for field, direction in requested:
            if field not in case.get("negotiable", []):
                continue
            current = main.get(field)
            options = (case.get("term_options") or {}).get(field) or []
            eligible = []
            for value in options:
                if direction == "lower" and (current is None or value >= current):
                    continue
                if direction == "higher" and (current is None or value <= current):
                    continue
                if field == "volume_per_year" and value > case["buyer"].get("need_per_year", value):
                    continue  # do not promise surplus purchases as a persuasion tactic
                key = self.trade_key(field, value)
                if key in s.offered_trade_keys:
                    continue
                terms = {**main, field: value}
                terms["unit_price"] = round(eco.price_for_value(case, terms, s.est, base_value), 2)
                terms = eco.quoted_offer(case, terms, s.std)
                if terms is None or not eco.must_haves_ok(case, terms, s.std):
                    continue
                cost = eco.deal_cost(case, terms, s.std, s.est)
                if cost is None or cost >= base_cost - 1.0:
                    continue
                eligible.append((cost, terms, field, value))
            if eligible:
                found.append(min(eligible, key=lambda row: (row[0], repr(sorted(row[1].items())))))
        found.sort(key=lambda row: (row[0], row[2], repr(row[3])))
        why_by_field = {
            "payment_days": "your request for earlier payment",
            "volume_per_year": "your request for a firm volume commitment",
            "lead_time_days": "your capacity constraint",
            "contract_months": "your capacity constraint and the value of planning security",
        }
        s.active_trades = [
            {"field": field, "value": value, "why": why_by_field.get(field, "your stated need")}
            for _, _, field, value in found[:2]
        ]
        for cost, _terms, field, value in found[:2]:
            self.note(
                s.sid,
                "need_trade_sheet",
                field=field,
                value=value,
                buyer_cost=round(cost, 2),
                main_cost=round(base_cost, 2),
                supplier_value=round(base_value, 2),
            )
        return [row[1] for row in found[:2]]

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
        families = set().union(*(self.claim_families(c) for c in claims)) if claims else set()
        s.pending = {
            "state": s.prev_state,
            "keys": keys,
            "families": families,
            "primary": dict(sheets[0]),
            "trade_keys": self.trade_keys(sheets),
        }
        statements = writer.statements(self.case, s, sheets)
        attachments = self.attachments(s)
        if s.state not in ("mirror",):
            s.ours.append(price)
            s.gaps.append(max(0.0, (theirs - price) / theirs) if theirs else 0.0)
            s.pending["appended"] = True
        tone = "warm" if s.prof.get("warm", True) else "friendly and businesslike"
        traded = any(n["what"] == "clause_trade" for n in self.notes)
        facts = self.team_facts(s, first, len(sheets) > 1 and s.state == "open")
        facts += writer.facts(self.case, s, claims, moved, statements, attachments, traded)
        para = llm.paragraph(
            self.complete,
            writer.brief(self.case, s.prof, latest(events).get("body"), facts, tone, first, [s.research, s.live]),
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
            "subject": writer.reply_subject(events, self.case),
            "body": body,
            "term_sheets": [{"terms": t} for t in sheets],
            "refs": refs,
        }
        if attachments:
            message["attachments"] = attachments
        return {"message": message}

    def fallback_move(self, sid, threads):
        """A safe template acknowledgement, without resending an unchanged binding offer."""
        s = self.sides.get(sid)
        events = threads[sid]
        statements = []
        if s and s.last_sent_terms:
            statements = writer.statements(self.case, s, [s.last_sent_terms])
        body = writer.fallback_email(statements)
        self.note(sid, "fallback", reason="template acknowledgement; no repeated sheet")
        return {
            "message": {
                "subject": writer.reply_subject(events, self.case),
                "body": body,
                "term_sheets": [],
                "refs": [],
            }
        }

    def commit(self, sid):
        """The message reached the supplier: its claims are spent."""
        s = self.sides[sid]
        if s.pending:
            self.used.update(s.pending["keys"])
            s.used_claim_families.update(s.pending.get("families", set()))
            s.offered_trade_keys.update(s.pending.get("trade_keys", set()))
            if s.pending.get("primary"):
                s.last_sent_terms = s.pending["primary"]
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
            live = live_threads(threads) or list(threads)
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


def step(last, theirs, conceded, first, fraction, budget, used, term_change=False):
    """Our next price after `last` against its counter `theirs`: we close `fraction` of the gap,
    hold low after a large first concession, and stay within the patience budget (`used` of it is
    spent). The real bidding and the demo bidding (`rehearsal.py`) both step with this."""
    gap = (theirs - last) / theirs
    share = fraction
    if first and conceded >= DEEP and not term_change:
        # a deep floor: a pure price drop this large means it moves fast on its own (job shops,
        # P05, D02) and agrees at our sheet next: hold the anchor (Dralveck agreed at a held
        # 27.86, at 28.07 after an 8 % step); a drop that came with terms it added (an index
        # clause, P08, P18) is not one
        share = 0.0
    left = max(0.0, budget - used)
    new_gap = min(gap * (1 - share), left / 2)
    if budget < 0.2:  # a touchy supplier: small, steady gaps
        new_gap = min(new_gap, 0.015)
    price = theirs * (1 - new_gap)
    price = max(price, last * (1 + MIN_MOVE))
    price = min(price, theirs * 0.998)
    return max(price, last)


def safe(fn, default=None):
    """`fn()`, or `default` when it raises: a hidden case may lack a field the data code expects,
    and a missing claim or profile must never cost the move."""
    try:
        return fn()
    except Exception:  # noqa: BLE001 - logged, the move goes on with the default
        log.exception("skipped: %s", getattr(fn, "__name__", fn))
        return default
