"""The case coordinator: one `Negotiator` per case. It prepares the brief (persona, estimate,
floor, anchor, target, levers and claim bank per supplier), keeps the blackboard every thread
reads, and owns the decision to close. The per-thread move is in `thread.py`. Code owns every
number and every binding decision; the model reads the supplier's prose and words our e-mail."""

import logging
import math
import threading

from arena_kit.agents import NaiveAgent
from arena_kit.data import DataPackage
from arena_kit.docs import standard_terms
from arena_kit.play import latest, live_threads, moves_left, standing

from . import claims, economics, llm, log, personas, thread

logger = logging.getLogger("buyer")

AGENTS = ("buyer", "naive")
# The case type sets the playbook: these levers come first, the persona's follow.
PLAYBOOK_LEVERS = {
    "quality": ["ppm_commitment", "chargeback_eur_per_complaint"],
    "capacity": ["volume_per_year", "contract_months", "lead_time_days"],
    "renewal": ["index_clause", "contract_months"],
    "raw_material": ["index_clause"],
    "price_increase": ["effective_date"],
    "bundling": ["volume_per_year"],
}


class Negotiator:
    def __init__(self, pkg=None, model=None):
        self.pkg, self.llm = pkg, model
        self.case, self.plan, self.bank = None, {}, None
        self.used_ids = set()  # cited anywhere in the case: each ID counts once per case
        self.lock = threading.Lock()

    # ---------- case open ----------

    def prepare(self, case, threads):
        """Before the clock matters: persona, estimate, floor, anchor, target, the lever analysis and
        the claim bank per supplier. With no threads yet (no session) the plan uses the current or
        fallback price in place of the quote, so it can be read before opening a case."""
        self.case, self.plan, self.used_ids = case, {}, set()
        self.bank = claims.ClaimBank(self.pkg, case)
        buyer = case["buyer"]
        trigger, asked = "", None
        if case.get("trigger_doc"):
            asked = (self.bank.fact(case["trigger_doc"]) or {}).get("asked_pct")
            if self.pkg:
                try:
                    trigger = self.pkg.document(case["trigger_doc"])
                except (FileNotFoundError, ValueError, KeyError):
                    trigger = ""
        part = (case.get("parts") or [None])[0]
        alt_terms = (buyer.get("alternative") or {}).get("terms") or {}
        proxy = buyer.get("current_unit_price") or alt_terms.get("unit_price") or buyer.get("fallback_unit_price")
        rivals = len(case.get("suppliers", [])) - 1
        for sid in case.get("suppliers", []):
            events = threads.get(sid, [])
            opening = latest(events) if events else {}
            name = _signature(opening.get("body", ""))
            persona = personas.build(self.pkg, sid, case) if self.pkg else personas.stranger(sid, case, name)
            if name and persona["name"] == sid:
                persona["name"] = name
            themes = claims.themes_in(trigger + " " + opening.get("body", ""))
            personas.refine(persona, opening.get("body", ""))
            std = standard_terms(events)
            sheet_id, qterms = standing(events) if events else (None, {})
            qprice = qterms.get("unit_price") or proxy
            cost_fact = self.bank.should_cost(part, sid) if part else None
            est = economics.supplier_estimate(case, persona, std, qprice, cost_fact and cost_fact[1])
            floor = economics.floor_price(case, persona, est, qprice) if qprice else None
            justified = (
                economics.justified_increase_pct(self.bank, part) if case.get("type") == "price_increase" else None
            )
            anchor = economics.anchor_price(case, persona, floor, qprice, justified) if qprice else None
            c_open = (
                economics.cost(case, qterms if sheet_id else {"unit_price": qprice}, std, est) if qprice else math.inf
            )
            bank_claims = self.bank.for_supplier(sid, persona, threads, themes)
            analysis = []
            if anchor:
                analysis = economics.lever_analysis(
                    case, persona, std, est, anchor, c_open, bank_claims, justified, asked, rivals
                )
            playbook = PLAYBOOK_LEVERS.get(case.get("type"), [])
            if buyer.get("category_goal") == "quality_first":
                playbook = PLAYBOOK_LEVERS["quality"] + playbook
            by_score = [r["lever"] for r in analysis if r["kind"] == "term"]
            negotiable = case.get("negotiable", [])
            levers = list(
                dict.fromkeys(
                    [lv for lv in playbook if lv in by_score]
                    + by_score
                    + [lv for lv in persona["levers"] if lv in negotiable and lv != "unit_price"]
                )
            )
            first = economics.sheets(case, std, est, anchor, levers, floor, standing=qterms or None) if anchor else []
            c_anchor = economics.cost(case, first[0], std, est) if first else c_open
            c_cap = None
            current = buyer.get("current_unit_price")
            if justified is not None and current and first:
                justified_price = round(current * (1 + max(0.0, justified) / 100), 2)
                c_cap = economics.cost(case, {**first[0], "unit_price": justified_price}, std, est)
            self.plan[sid] = {
                "persona": persona,
                "std": std,
                "est": est,
                "floor": floor,
                "anchor": anchor,
                "justified_pct": justified,
                "asked_pct": asked,
                "c_open": c_open,
                "target": economics.target_cost(case, c_open, c_anchor, c_cap) if c_open < math.inf else math.inf,
                "levers": levers,
                "analysis": analysis,
                "themes": themes,
                "dropped": set(),
                "claims": bank_claims,
                "used_ids": set(),
                "rounds": [],
                "hold": {},
                "price_pushes": 0,
                "final_packages": 0,
                "subject": opening.get("subject") or case.get("title", ""),
                "pre_session": not events,
            }
            log.plan(
                {
                    "case": case["case_id"],
                    "supplier": sid,
                    "pre_session": not events,
                    "archetype": persona["archetype"],
                    "tier": persona["importance"]["tier"],
                    "signals": persona["signals"],
                    "estimate": est,
                    "floor": floor,
                    "anchor": anchor,
                    "quote": qprice,
                    "justified_pct": justified,
                    "asked_pct": asked,
                    "c_open": c_open,
                    "target": self.plan[sid]["target"],
                    "levers": levers,
                    "analysis": analysis,
                    "claims": [c["ids"] for c in bank_claims[:6]],
                }
            )
            logger.info(
                "%s %s: %s/%s tier=%s floor=%s anchor=%s quote=%s target=%.0f c_open=%.0f",
                case["case_id"],
                sid,
                persona["archetype"],
                persona["tone"],
                persona["importance"]["tier"],
                floor,
                anchor,
                qprice,
                self.plan[sid]["target"],
                c_open,
            )
            for r in analysis:
                logger.info("  lever %s", economics.lever_line(r))

    # ---------- one move in one thread ----------

    def decide_thread(self, case, threads, sid):
        """{"kind": "send", "message": ...} | {"kind": "accept"} | {"kind": "wait"} | {"kind": "drop"}."""
        return thread.decide(self, case, threads, sid)

    # ---------- closing across threads ----------

    def standing_cost(self, case, threads, sid):
        p = self.plan[sid]
        sheet_id, terms = standing(threads[sid])
        std = standard_terms(threads[sid]) or p["std"]
        return economics.cost(case, terms, std, p["est"]) if sheet_id else math.inf

    def best_accept(self, case, threads):
        """The cheapest standing sheet across live threads that passes the gate, as an accept move."""
        best = None
        for sid in live_threads(threads):
            if sid not in self.plan:
                continue
            p = self.plan[sid]
            sheet_id, terms = standing(threads[sid])
            std = standard_terms(threads[sid]) or p["std"]
            if sheet_id and economics.gate_ok(case, terms, std, p["est"]):
                c = economics.cost(case, terms, std, p["est"])
                if best is None or c < best[0]:
                    best = (c, sid, sheet_id)
        if best is None:
            return None
        return {"supplier_id": best[1], "message": {"action": {"type": "accept", "term_sheet_id": best[2]}}}

    def cheaper_thread_moving(self, case, threads, sid):
        """RFQ rule: never accept while a cheaper thread is still open and has moves left."""
        mine = self.standing_cost(case, threads, sid)
        for other in live_threads(threads):
            if other == sid or other not in self.plan:
                continue
            status = latest(threads[other]).get("status")
            if status == "open" and moves_left(case, threads[other]) > 0:
                if self.standing_cost(case, threads, other) < mine:
                    return True
        return False

    def decide(self, case, threads):
        """The kit's one-move interface (`arena_kit.play`): threads take turns, closing goes through best_accept."""
        if self.case is None or self.case.get("case_id") != case.get("case_id"):
            self.prepare(case, threads)
        live = [s for s in live_threads(threads) if not self.plan.get(s, {}).get("stopped")]
        while live:
            sid = min(live, key=lambda s: sum(m.get("from") == "buyer" for m in threads[s]))
            d = self.decide_thread(case, threads, sid)
            if d["kind"] == "send":
                return {"supplier_id": sid, "message": d["message"]}
            if d["kind"] == "accept" and not self.cheaper_thread_moving(case, threads, sid):
                best = self.best_accept(case, threads)
                if best:
                    return best
            self.plan[sid]["stopped"] = True
            live.remove(sid)
        best = self.best_accept(case, threads)
        return best or {"supplier_id": live_threads(threads)[0], "message": {"action": {"type": "walk_away"}}}

    # ---------- after the case ----------

    def after_case(self, case, threads, result):
        for sid, p in self.plan.items():
            events = threads.get(sid, [])
            checks = {}
            for m in events:
                for c in m.get("claim_results") or []:
                    checks[c.get("result")] = checks.get(c.get("result"), 0) + 1
            log.case(
                {
                    "case": case["case_id"],
                    "supplier": sid,
                    "archetype": p["persona"]["archetype"],
                    "deal": bool(result.get("deal")) and result.get("supplier_id") == sid,
                    "score": result.get("score"),
                    "c_open": result.get("c_open"),
                    "c_deal": result.get("c_deal"),
                    "c_best": result.get("c_best"),
                    "target": p["target"],
                    "rounds": len(p["rounds"]),
                    "statuses": [m.get("status") for m in events if m.get("from") != "buyer"],
                    "claims": checks,
                    "latency_s": [r["latency_s"] for r in p["rounds"]],
                    "replay": result.get("replay_url"),
                }
            )


def _signature(body):
    """The last non-empty line of a supplier's e-mail: usually the company name."""
    lines = [ln.strip() for ln in (body or "").splitlines() if ln.strip()]
    return lines[-1][:80] if lines else None


def agent_factory(name, data=None, model=None):
    """A function that returns a fresh agent per case. `data`: the unpacked data package;
    `model`: an `llm.LLM` (default: from .env via `llm.from_env`, None for template moves only)."""
    if name == "naive":
        return NaiveAgent
    package = None
    if data:
        package = DataPackage(data)
        package.lookup("")  # build the ID index once, before parallel agents share it
    if model is None:  # False: no model, template moves only
        model = llm.from_env()
    return lambda: Negotiator(package, model or None)
