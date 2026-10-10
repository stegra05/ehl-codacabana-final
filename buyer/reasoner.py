"""The reasoner: the code policy with a model in two places, both bounded. It reads each supplier
reply into a fixed schema (`reader`: asks, levers, refusals, which claim kinds counted), and it
chooses the next move from a menu the code computes: every option is a complete sheet priced with
`total_cost`, inside the floor and ceiling of the thread (never at or above the supplier's standing
price, never above the price where C reaches the alternative, never below our last sheet), with the
claims ranked by what the supplier counted. The model picks an option id and how many claims; an
invalid, late or missing answer takes the code policy's own move. Prices, terms and the accept gate
never leave the code.

Levers: when the supplier names a term it would pay for ("Faster payment is welcome; we can reflect
it in the price"), the menu holds that trade at a price between what the term is worth to us
(`economics.indifference_price`) and what it is worth to the supplier (`price_for_value`), so the
trade pays both sides by our arithmetic."""

import json
import logging
import re
import time

from arena_kit.play import latest

from . import economics as eco
from . import llm, reader, writer
from .policy import FIRST_CLAIMS, LATER_CLAIMS, MIN_MOVE, Negotiator, safe

log = logging.getLogger("buyer")

# The price step itself stays the code policy's (30 % of the gap, tuned on 100+ sessions): offered a
# 15 % step the model took it in 75 of 82 simulator decisions and the suppliers' final offers then
# came while we were far away (mean 0.73 against 0.80). The model decides trades and claims.
TYPICAL_PATIENCE = 0.4  # cumulative gap at which a typical supplier gave its final offer (learnings, takeaway 4)
KEEP = 0.7  # the share of a trade's surplus we keep (the supplier still gains the rest by our estimate)
READ_SHARE, DECIDE_SHARE = 0.3, 0.3  # of the model wall clock for this move; the writer gets the rest
IMPORTANCE = {  # what the supplier is to us, and how that shapes the tactic
    "strategic": "strategic: relationship goal or our only source; small steady steps, never squeeze below its cost",
    "important": "important: an A or B supplier we want to keep; firm on price, generous on terms that are free for us",
    "standard": "standard: a replaceable supplier; price first, data-backed, quick close",
}

SYSTEM = """You are the senior buyer of Hollerau Pumpenwerke, a German pump maker, in an e-mail price
negotiation. Our purchasing code computed the moves allowed this round (the price step is fixed by
code); pick ONE option id and how many data arguments (1 to 3) to cite. What these suppliers do: data
they "took into account" lowers where they stop, dismissed kinds do not, so cite more when kinds they
count are left and one when only dismissed kinds remain; a term they asked for is worth more to them
than a price step of the same cost, so take a trade they named unless their e-mail shows they would
not honour it; never go below the relationship target. Prefer the lowest C among moves the supplier
will plausibly accept this round.
Reply with ONLY this JSON, nothing else: {"option": "<id>", "claims": <1-3>, "reason": "<one short sentence>"}"""


class Reasoner(Negotiator):
    # -- the context window, built once per thread ------------------------------------------------
    def setup(self, sid, events):
        s = super().setup(sid, events)
        if s.state != "ended":
            s.importance = self.importance(s)
            s.context = safe(lambda: self.context(s), "")
            self.note(sid, "context", importance=s.importance, chars=len(s.context))
        return s

    def importance(self, s):
        case = self.case
        if case["buyer"].get("category_goal") in eco.RELATIONSHIP_GOALS or eco.c_alt(case) == float("inf"):
            return "strategic"
        rows = self.bank.query("SELECT abc_class FROM suppliers WHERE id = ?", (s.sid,))
        if rows and (rows[0].get("abc_class") or "C") in ("A", "B"):
            return "important"
        return "standard"

    def context(self, s):
        """Need, costs, market, supplier intel and competition for this thread: what the chooser
        sees every round besides the live path."""
        case, b = self.case, self.case["buyer"]
        alt = b.get("alternative") or {}
        c_alt = eco.c_alt(case)
        lines = [
            f"OUR NEED: {b.get('need_per_year')} units a year over {b.get('horizon_years')} years; lead time needed "
            f"{b.get('need_lead_time_days')} days; must-haves {b.get('must_haves') or 'none'}; current price "
            f"{b.get('current_unit_price')}; fallback {b.get('fallback_unit_price')} plus "
            f"{b.get('fallback_risk_pct')} % risk; alternative {alt.get('kind') or 'none'}"
            + (f" at C {c_alt:,.0f}" if c_alt != float("inf") else ""),
            f"COSTS: its full cost (our estimate) {s.est.get('full_cost')}; its cost of money "
            f"{s.est.get('interest_rate')}/yr; ours {b.get('interest_rate')}/yr at {b.get('reference_payment_days')} "
            f"days reference; the price at which C is lowest for us {s.target}",
        ]
        market = []
        for part in case.get("parts") or []:
            for series in self.bank.drivers(part):
                move = self.bank.move12(series)
                fall = self.bank.index_change(series)
                market.append(
                    f"{series} {move * 100:+.1f} % over 12 months"
                    + (f", {fall['text'].split(' changed ')[1].split(' (')[0]}" if fall else "")
                    if move is not None
                    else series
                )
        if market:
            lines.append("MARKET (its cost drivers): " + "; ".join(market))
        intel = self.bank.query(
            "SELECT i.owner_type, i.staff, i.turnover_band, i.credit_index, s.abc_class, s.category "
            "FROM supplier_intel i JOIN suppliers s ON s.id = i.supplier_id WHERE i.supplier_id = ?",
            (s.sid,),
        )
        who = {k: v for k, v in (intel[0] if intel else {}).items() if v is not None}
        pay = f"; we paid {s.pay_record[1]} of its last {s.pay_record[0]} invoices late" if s.pay_record else ""
        lines.append(
            f"SUPPLIER: {who or s.prof.get('owner_type') or 'unknown'}; traits {s.prof.get('signals') or 'none'}{pay}"
        )
        rivals = [c["text"] for c in s.claims if c["kind"] == "rival"]
        if rivals:
            lines.append("COMPETITION: " + " ".join(rivals))
        return "\n".join(lines)

    def patience(self, s):
        """How much of the supplier's patience our path has used, and how it is conceding."""
        used = sum(s.gaps)
        limit = min(s.budget, TYPICAL_PATIENCE)
        counters = max(0, len(s.theirs) - 1)
        trend = ""
        if len(s.theirs) >= 3:
            last, before = s.theirs[-2] - s.theirs[-1], s.theirs[-3] - s.theirs[-2]
            trend = f"; its last step {last:.2f} against {before:.2f} before" + (
                " (shrinking)" if last < before else ""
            )
        return (
            f"cumulative gap {used * 100:.0f} % of about {limit * 100:.0f} % before a final offer; "
            f"{counters} counters so far (typical 3 to 6){trend}"
        )

    def read_reply(self, s, last):
        budget = self.writer_s * READ_SHARE
        t0 = time.monotonic()
        s.read = reader.read(self.complete, last.get("body"), budget)
        secs = round(time.monotonic() - t0, 1)
        self.writer_s = max(0.0, self.writer_s - secs)
        self.note(s.sid, "reader", source=s.read.get("source"), secs=secs, fallback=s.read.get("fallback"))
        self.absorb(s)

    # -- the menu --------------------------------------------------------------------------------
    def bounds(self, s, theirs):
        lo = s.ours[-1] * (1 + MIN_MOVE) if s.ours else s.anchor
        hi = theirs * 0.998
        if s.ceiling:
            hi = min(hi, s.ceiling)
        return round(lo, 2), round(hi, 2)

    def menu(self, s, theirs, left):
        """Every move the code allows this round, each a complete sheet with its price and C."""
        case = self.case
        lo, hi = self.bounds(s, theirs)
        base_price, n = self.next_price(s, theirs)
        out = []

        def add(oid, terms, price, note, claims=n):
            price = round(min(max(price, lo if terms == s.terms else 0.0), hi if terms == s.terms else price), 2)
            sheet = eco.at_price(terms, price)
            if not eco.must_haves_ok(case, sheet, s.std):
                return
            c = eco.cost(case, sheet, s.std, s.est)
            out.append({"id": oid, "terms": terms, "price": price, "c": c, "note": note, "claims": claims})

        if not s.ours:
            add("step", s.terms, base_price, "our opening at the planned terms", FIRST_CLAIMS)
        else:
            add("step", s.terms, base_price, "the planned step toward its counter at our terms")
            if s.target and lo <= s.target <= hi:
                add("target", s.terms, s.target, "the price where our C is lowest (relationship charge included)")
        for trade in self.trades(s, theirs, base_price):
            out.append(trade)
        seen, uniq = set(), []
        for o in out:  # one option per (price, terms)
            key = (o["price"], repr(sorted((k, repr(v)) for k, v in o["terms"].items() if k != "unit_price")))
            if key not in seen:
                seen.add(key)
                uniq.append(o)
        return uniq

    def trades(self, s, theirs, base_price):
        """The levers the supplier named, priced so the package costs us less than the plain step
        and is worth more to the supplier (a trade it did not ask for rests on our estimate alone:
        the planner already took those at setup)."""
        case = self.case
        fields = [f for f in s.levers if f in case["negotiable"] and f not in s.refused]
        if not s.ours or not fields:
            return []
        rows = eco.lever_trades(case, s.terms, base_price, s.std, s.est, fields)
        rows = [r for r in rows if r["surplus"] > 0]
        out = []
        for r in rows[:3]:
            price = round(r["theirs"] + (1 - KEEP) * r["surplus"], 2)
            # its standing sheet at the new terms: our price must stay below it
            their_value = eco.value(case, eco.at_price(s.terms, theirs), s.est)
            theirs_new = eco.price_for_value(case, r["terms"], s.est, their_value)
            price = min(price, round(theirs_new * 0.998, 2))
            if s.ceiling:
                price = min(price, eco.ceiling(case, r["terms"], s.std, s.est, s.ceiling))
            sheet = eco.at_price(r["terms"], price)
            if price <= 0 or not eco.must_haves_ok(case, sheet, s.std):
                continue
            out.append(
                {
                    "id": f"trade:{r['field']}={r['value']}",
                    "terms": r["terms"],
                    "price": price,
                    "c": eco.cost(case, sheet, s.std, s.est),
                    "note": f"{r['field']} {s.terms.get(r['field'])} -> {r['value']} (it named this lever)",
                    "claims": LATER_CLAIMS,
                    "trade": (r["field"], r["value"]),
                }
            )
        return out

    # -- the choice -------------------------------------------------------------------------------
    def brief(self, s, menu, events, theirs, left):
        case = self.case
        step = next((o for o in menu if o["id"] == "step"), menu[0])
        pairs = zip(s.ours, s.theirs, strict=False)
        rounds = " | ".join(f"r{i + 1}: ours {o} theirs {t}" for i, (o, t) in enumerate(pairs))
        lines = [
            f"CASE: {case.get('title')}; goal {case['buyer'].get('category_goal')}; messages left {left}",
            f"WE ARE: {writer.PERSONA.get(case['buyer'].get('category_goal'), 'a professional buyer')}",
            f"THE SUPPLIER IS {IMPORTANCE.get(getattr(s, 'importance', 'standard'))}",
            getattr(s, "context", ""),
            f"PATH: {rounds or 'none yet'}; its standing price at our terms {theirs}",
            f"PATIENCE: {self.patience(s)}",
            f"BOUNDS: floor (its cost, our estimate) {s.floor}; ceiling (our alternative) {s.ceiling}; "
            f"relationship target {s.target}",
            f"ITS REPLY READS: asks {s.read.get('asks')}, levers {s.read.get('levers')}, "
            f"refused {s.read.get('refused')}, counted {sorted(s.counted)}, dismissed {sorted(s.dismissed)}, "
            f"final {s.read.get('final')}",
            f"ITS LAST E-MAIL (start): {(latest(events).get('body') or '')[:500]}",
            f"CLAIMS LEFT: {[c['kind'] for c in self.unused(s)]}",
            "OPTIONS (C = our total cost over the horizon, lower is better):",
        ]
        for o in menu:
            saving = step["c"] - o["c"]
            lines.append(
                f"- {o['id']}: EUR {o['price']:.2f}, {o['note']}; C {o['c']:,.0f}"
                + (f" ({saving:+,.0f} against step)" if o is not step else "")
            )
        return "\n".join(lines)

    def unused(self, s):
        return [c for c in s.claims if not any(i in self.used for i in c["ids"])]

    def choose(self, s, menu, events, theirs, left):
        default = next((o for o in menu if o["id"] == "step"), menu[0])
        if self.complete is None or len(menu) < 2:
            return default
        budget = self.writer_s * DECIDE_SHARE
        if budget < llm.MIN_S:
            return default
        t0 = time.monotonic()
        try:
            brief = self.brief(s, menu, events, theirs, left)
            text = llm.POOL.submit(llm.fast(self.complete), SYSTEM, brief).result(timeout=min(budget, llm.TIMEOUT_S))
            m = re.search(r"\{.*\}", text or "", re.S)
            data = json.loads(m.group(0)) if m else {}
        except Exception as e:  # noqa: BLE001 - a slow or broken model takes the code's move
            log.warning("reasoner model failed after %.1fs: %s", time.monotonic() - t0, e)
            data = {}
        secs = round(time.monotonic() - t0, 1)
        self.writer_s = max(0.0, self.writer_s - secs)
        chosen = next((o for o in menu if o["id"] == data.get("option")), None)
        if chosen is None:
            self.note(s.sid, "reason", option="step", why="invalid or no answer", answer=str(data)[:200], secs=secs)
            return default
        n = data.get("claims")
        if isinstance(n, int) and 1 <= n <= 3:
            chosen = {**chosen, "claims": n}
        why = str(data.get("reason", ""))[:300]
        self.note(s.sid, "reason", option=chosen["id"], claims=chosen["claims"], why=why, secs=secs)
        return chosen

    def decide(self, s, sheets, events, theirs, left, threads):
        menu = self.menu(s, theirs, left)
        if not menu:
            return super().decide(s, sheets, events, theirs, left, threads)
        choice = self.choose(s, menu, events, theirs, left)
        if choice.get("trade"):
            field, value = choice["trade"]
            word = field.split("_")[0]
            lines = (latest(events).get("body") or "").split("\n")
            said = next((line for line in lines if word in line.lower()), "")
            self.switch(s, choice["terms"], f"its lever {field}")
            s.trade = (field, said.strip()[:160])
        price = min(choice["price"], round(s.theirs[-1] * 0.998, 2)) if s.ours else choice["price"]
        claims = self.pick(s, choice["claims"], threads)
        return self.send(s, [eco.at_price(s.terms, price)], claims, events, s.theirs[-1])
