"""The buyer agent, one per case. Code owns every number and every binding decision: the floor,
the anchor, the sheets, the concessions, the accept. The model reads the supplier's prose into
signals and words our e-mail. The supplier's persona sets the lever, the tone and how hard we push.
"""

import logging
import math
import re
import threading
import time

from arena_kit.docs import standard_terms
from arena_kit.play import ENDED, latest, live_threads, moves_left, standing

from . import claims, economics, guard, log, personas

logger = logging.getLogger("negotiator")

APPROVAL = re.compile(r"approv|head[- ]office|management|headquarters|my boss|the owner", re.I)
REJECT = re.compile(r"not our reality|does not apply|not relevant|irrelevant|nothing to do with", re.I)
COOL = re.compile(r"regret|unfortunately|disappoint|cannot accept|surprised", re.I)
INTEREST = {
    "payment_days": re.compile(r"payment|cash|liquidity|days net|skonto", re.I),
    "volume_per_year": re.compile(r"volume|quantit|pieces a year|units a year", re.I),
    "contract_months": re.compile(r"contract (term|length)|long-term|multi-year|months|years", re.I),
    "effective_date": re.compile(r"valid from|effective|from \d{4}-\d{2}", re.I),
    "lead_time_days": re.compile(r"lead time|delivery date|schedule", re.I),
    "index_clause": re.compile(r"index|surcharge|escalat", re.I),
    "tooling_eur": re.compile(r"tooling|tool cost", re.I),
    "ppm_commitment": re.compile(r"ppm|defect|8d", re.I),
}
# The case type sets the playbook: these levers come first, the persona's follow.
PLAYBOOK_LEVERS = {
    "quality": ["ppm_commitment", "chargeback_eur_per_complaint"],
    "capacity": ["volume_per_year", "contract_months", "lead_time_days"],
    "renewal": ["index_clause", "contract_months"],
    "raw_material": ["index_clause"],
    "price_increase": ["effective_date"],
    "bundling": ["volume_per_year"],
}
GOAL_WORDS = {
    "leverage": "leverage: the best total cost, firm and factual",
    "routine": "routine: a fair deal quickly, no long fight",
    "stabilise": "stabilise: keep this strategic supplier healthy, trade security rather than squeeze price",
    "secure_supply": "secure supply: cover the full need and protect lead time, never risk the relationship",
    "quality_first": "quality first: a ppm commitment and chargebacks matter more than the last euro",
}


class Negotiator:
    def __init__(self, pkg=None, llm=None, kb=True):
        self.pkg, self.llm, self.kb = pkg, llm, kb
        self.case, self.plan, self.bank = None, {}, None
        self.lock = threading.Lock()

    # ---------- case open ----------

    def prepare(self, case, threads):
        """Before the clock matters: persona, estimate, floor, anchor, target and claims per supplier."""
        self.case, self.plan = case, {}
        self.bank = claims.ClaimBank(self.pkg, case)
        trigger = ""
        if case.get("trigger_doc") and self.pkg:
            try:
                trigger = self.pkg.document(case["trigger_doc"])
            except (FileNotFoundError, ValueError, KeyError):
                trigger = ""
        part = (case.get("parts") or [None])[0]
        for sid in case.get("suppliers", []):
            events = threads.get(sid, [])
            opening = latest(events) if events else {}
            name = _signature(opening.get("body", ""))
            persona = personas.load(sid) if self.kb else None
            if not persona:
                persona = personas.build(self.pkg, sid, None, case) if self.pkg else personas.stranger(sid, case, name)
                if name and persona["name"] == sid:
                    persona["name"] = name
                if self.kb:
                    personas.save(persona)
            std = standard_terms(events)
            sheet_id, qterms = standing(events)
            qprice = qterms.get("unit_price")
            est = economics.supplier_estimate(self.pkg, case, persona, std, qprice)
            floor = economics.floor_price(case, persona, est, qprice) if qprice else None
            justified = (
                economics.justified_increase_pct(self.bank, part)
                if case.get("type") == "price_increase" and part
                else None
            )
            anchor = economics.anchor_price(case, persona, floor, qprice, justified) if qprice else None
            c_open = economics.cost(case, qterms, std, est) if sheet_id else math.inf
            playbook = PLAYBOOK_LEVERS.get(case.get("type"), [])
            if case["buyer"].get("category_goal") == "quality_first":
                playbook = PLAYBOOK_LEVERS["quality"] + playbook
            levers = [lv for lv in playbook + persona["levers"] if lv in case.get("negotiable", [])]
            levers = list(dict.fromkeys(levers))
            themes = claims.themes_in(trigger + " " + opening.get("body", ""))
            first = economics.sheets(case, persona, std, est, anchor, levers, floor, standing=qterms) if anchor else []
            c_anchor = economics.cost(case, first[0], std, est) if first else c_open
            self.plan[sid] = {
                "persona": persona,
                "std": std,
                "est": est,
                "floor": floor,
                "anchor": anchor,
                "justified_pct": justified,
                "c_open": c_open,
                "target": economics.target_cost(case, c_open, c_anchor) if c_open < math.inf else math.inf,
                "levers": levers,
                "themes": themes,
                "dropped": set(),
                "claims": self.bank.for_supplier(sid, persona, threads),
                "used_ids": set(),
                "rounds": [],
                "hold": {},
                "price_pushes": 0,
                "final_packages": 0,
                "observations": [],
                "subject": opening.get("subject") or case.get("title", ""),
            }
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

    # ---------- one move in one thread ----------

    def decide_thread(self, case, threads, sid):
        """{"kind": "send", "message": ...} | {"kind": "accept"} | {"kind": "drop"}."""
        p = self.plan[sid]
        persona, rel = p["persona"], p["persona"]["relationship"]
        events = threads[sid]
        last = latest(events)
        status = last.get("status")
        if status in ENDED:
            return {"kind": "drop", "why": status}
        t0 = time.monotonic()
        std = standard_terms(events) or p["std"]
        p["std"] = std
        sheet_id, theirs = standing(events)
        t_price = theirs.get("unit_price")
        est = p["est"]
        c_theirs = economics.cost(case, theirs, std, est) if sheet_id else math.inf

        reading = self._read(p, last)
        p["observations"].append(reading)
        p["dropped"] |= set(reading.get("rejected_themes") or [])
        p["themes"] = list(dict.fromkeys((reading.get("cost_driver_themes") or []) + p["themes"]))
        for field in reading.get("interested_in") or []:
            if field in p["levers"]:
                p["levers"].remove(field)
                p["levers"].insert(0, field)
        prev = p["rounds"][-1] if p["rounds"] else None
        moved = bool(prev and prev["theirs"] is not None and t_price is not None and t_price < prev["theirs"] - 0.005)
        if prev and prev["sheets"] and len(prev["sheets"]) > 1:
            answered = personas._lever_answered(prev["sheets"], theirs)
            if answered:
                lever = next(
                    (k for k in answered if k != "unit_price" and answered[k] != prev["sheets"][0].get(k)), None
                )
                if lever:
                    p["hold"][lever] = theirs.get(lever, answered[lever])
                    p["lever_answered"] = lever
        gate = economics.gate_ok(case, theirs, std, est) if sheet_id else False
        left = moves_left(case, events)
        near = c_theirs <= p["target"] + 0.25 * max(0.0, p["c_open"] - p["target"])

        if status == "agreed":
            return {"kind": "accept"} if gate else {"kind": "drop", "why": "agreed terms fail the gate"}
        if sheet_id and gate and c_theirs <= p["target"]:
            return {"kind": "accept"}
        if left <= 0:
            return {"kind": "accept"} if gate else {"kind": "drop", "why": "round limit, gate fails"}
        if status == "final_offer":
            if gate and (rel["protect"] or p["final_packages"] >= 1 or left <= 1 or near):
                return {"kind": "accept"}
            if p["final_packages"] >= 1:
                return {"kind": "accept"} if gate else {"kind": "drop", "why": "final offer fails the gate"}
            p["final_packages"] += 1
            price = t_price
            sheets = economics.sheets(
                case, persona, std, est, price, p["levers"], p["floor"], standing=theirs, hold=p["hold"]
            )
            if all(economics.cost(case, s, std, est) >= c_theirs for s in sheets):
                return {"kind": "accept"} if gate else {"kind": "drop", "why": "no package beats the final offer"}
            move = (
                "They sent their final offer. We do not push the price: we accept their price level "
                "and ask for one package on the other terms."
            )
            return self._send(
                case, threads, sid, p, sheets, status, reading, moved, move, t0, n_claims=1, question=None
            )

        round_idx = len(p["rounds"])
        if round_idx == 0:
            price = p["anchor"]
            move = (
                "Our opening: the first package is our anchor; the others trade the price against terms "
                "the supplier may value."
            )
        else:
            close_in = p["price_pushes"] >= rel["max_price_pushes"] or left <= 1
            price = economics.concession(prev["price"], t_price, round_idx - 1, moved, close_in)
            if left <= 1:
                move = "Our best and final package: we move clearly toward them so this can close."
            elif close_in:
                move = "We move most of the way toward them to close soon; we value the relationship."
            elif moved:
                move = "They moved, so we move a step toward them and keep the package they answered."
            else:
                move = "They did not move, so we hold our price, vary the package and add one argument or a question."
        if t_price:
            price = min(price, t_price)
        sheets = economics.sheets(
            case, persona, std, est, price, p["levers"], p["floor"], standing=theirs, hold=p["hold"]
        )
        if sheet_id and gate and all(economics.cost(case, s, std, est) >= c_theirs for s in sheets):
            return {"kind": "accept"}
        if price < (t_price or math.inf):
            p["price_pushes"] += 1
        question = self._question(case, p, round_idx, reading)
        return self._send(
            case,
            threads,
            sid,
            p,
            sheets,
            status,
            reading,
            moved,
            move,
            t0,
            n_claims=2 if round_idx == 0 else 1,
            question=question,
        )

    def _send(self, case, threads, sid, p, sheets, status, reading, moved, move, t0, n_claims, question):
        persona = p["persona"]
        picked = claims.ClaimBank.pick(p["claims"], p["used_ids"], p["themes"], p["dropped"], n=n_claims)
        if len(case.get("suppliers", [])) > 1 and persona["relationship"].get("cite_rivals", True) and len(picked) < 3:
            rivals = [c for c in self.bank.rival_claims(sid, threads) if not any(i in p["used_ids"] for i in c["ids"])]
            if rivals:
                picked.append(max(rivals, key=lambda c: -c["figure"]))
        ids = {i for c in picked for i in c["ids"]}
        sheets_text = [economics.describe(case, s) for s in sheets]
        ack = _ack(moved, p.get("lever_answered"), reading)
        body, used_llm = None, False
        if self.llm:
            brief = self._brief(
                case, p, latest(threads[sid]), status, reading, sheets_text, picked, question, move, ack
            )
            draft = self.llm.write_email(brief)
            body = guard.check(draft, ids, sheets, picked) if draft else None
            used_llm = body is not None
        if not body:
            body = guard.template(
                persona["name"], sheets_text, picked, question, ack, opening=not p["rounds"], tone=persona["tone"]
            )
        p["rounds"].append(
            {
                "price": sheets[0].get("unit_price"),
                "theirs": standing(threads[sid])[1].get("unit_price"),
                "status": status,
                "moved": moved,
                "sheets": sheets,
                "claims": [c["ids"] for c in picked],
                "latency_s": round(time.monotonic() - t0, 1),
                "llm": used_llm,
            }
        )
        p["used_ids"] |= ids
        log.move(
            {
                "case": case["case_id"],
                "supplier": sid,
                "round": len(p["rounds"]),
                "status_in": status,
                "sheets": sheets,
                "c_sheets": [economics.cost(case, s, p["std"], p["est"]) for s in sheets],
                "claims": sorted(ids),
                "move": move,
                "llm": used_llm,
                "latency_s": p["rounds"][-1]["latency_s"],
                "mood": reading.get("mood"),
                "themes": p["themes"],
            }
        )
        subject = p["subject"] if p["subject"].lower().startswith("re:") else f"Re: {p['subject']}"
        return {
            "kind": "send",
            "message": {
                "subject": subject[:300],
                "body": body,
                "term_sheets": [{"terms": s} for s in sheets],
                "refs": sorted(ids)[:20],
            },
        }

    # ---------- reading and writing ----------

    def _read(self, p, msg):
        body = msg.get("body", "") or ""
        if self.llm:
            out = self.llm.read_reply(p["persona"]["name"], body, msg.get("status"), msg.get("claim_results"))
            if out:
                return out
        rejected = set()
        if REJECT.search(body) and p["rounds"]:
            rejected = {c["theme"] for c in p["claims"] if any(i in p["used_ids"] for i in c["ids"])}
        return {
            "summary": body.strip().replace("\n", " ")[:200],
            "stated_reasons": [],
            "cost_driver_themes": claims.themes_in(body),
            "interested_in": [f for f, rx in INTEREST.items() if rx.search(body)],
            "rejected_themes": sorted(rejected),
            "needs_approval": bool(APPROVAL.search(body)),
            "mood": "cool" if COOL.search(body) else "neutral",
            "walk_risk": "high" if msg.get("status") == "final_offer" else "low",
            "questions_to_us": [],
            "offers_document": "",
            "cheaper_variant": "",
        }

    def _question(self, case, p, round_idx, reading):
        offered = (reading.get("offers_document") or "").lower()
        kind = case.get("type")
        if round_idx == 0:
            if kind == "quality" or case["buyer"].get("category_goal") == "quality_first":
                return None if "8d" in offered else "Could you send us the 8D report for the open complaints?"
            if kind == "capacity":
                return (
                    None if "schedule" in offered else "Could you send us your delivery schedule for the coming months?"
                )
            if "breakdown" in offered:
                return None
            soft = p["persona"]["relationship"]["protect"]
            return (
                "Could you share your cost breakdown for this part, so we understand the drivers together?"
                if soft
                else "Could you send us your cost breakdown for this part?"
            )
        if round_idx == 1 and not reading.get("cheaper_variant"):
            return "Is there a variant of the part or the process that would be cheaper for both of us?"
        if round_idx == 2 and p.get("lever_answered") is None and p["levers"]:
            return "Which of the terms matters most on your side, so we can shape the package around it?"
        return None

    def _brief(self, case, p, last, status, reading, sheets_text, picked, question, move, ack):
        persona = p["persona"]
        arch = personas.ARCHETYPES.get(persona["archetype"], {})
        digest = persona.get("digest") or {}
        lines = [
            f"TONE: {persona['tone']}",
            f"SUPPLIER: {persona['name']} ({persona.get('country') or 'country unknown'}; "
            f"{persona['importance']['tier']} supplier; {arch.get('about', '')}).",
            f"AVOID: {', '.join(persona.get('avoid') or []) or 'nothing special'}.",
        ]
        if digest.get("situation"):
            lines.append(
                f"THEIR SITUATION: {digest['situation']} Moves them: {', '.join(digest.get('what_moves_them') or [])}."
            )
        notes = (persona.get("learned") or {}).get("notes") or []
        if notes:
            lines.append("LESSONS FROM EARLIER CASES: " + " ".join(notes[-3:]))
        lines += [
            f"CASE: {case.get('title')} ({case.get('type')}). "
            f"Our goal: {GOAL_WORDS.get(case['buyer'].get('category_goal'), '')}.",
            f"THEIR LAST E-MAIL (status {status}):\n{(last.get('body') or '')[:1800]}",
            f"WHAT WE TOOK FROM IT: {reading.get('summary', '')} "
            f"Themes they named: {', '.join(reading.get('cost_driver_themes') or []) or 'none'}.",
        ]
        if ack:
            lines.append(f"ACKNOWLEDGE: {ack}")
        lines.append(f"OUR MOVE: {move}")
        lines.append("OPTIONS (state exactly these figures):")
        lines += [f"- Option {chr(65 + i)}: {t}" for i, t in enumerate(sheets_text)]
        lines.append(
            "DATA ARGUMENTS (include each sentence word for word, IDs included):"
            if picked
            else "DATA ARGUMENTS: none this time."
        )
        lines += [f"- {c['sentence']}" for c in picked]
        lines.append(f"QUESTION TO ASK: {question or 'none'}")
        return "\n".join(lines)

    # ---------- closing across threads ----------

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

    def decide(self, case, threads):
        """The kit's one-move interface (`arena_kit.play`): threads take turns, closing goes through best_accept."""
        if self.case is None or self.case.get("case_id") != case.get("case_id"):
            self.prepare(case, threads)
        live = [s for s in live_threads(threads) if not self.plan.get(s, {}).get("dropped")]
        while live:
            sid = min(live, key=lambda s: sum(m.get("from") == "buyer" for m in threads[s]))
            d = self.decide_thread(case, threads, sid)
            if d["kind"] == "send":
                return {"supplier_id": sid, "message": d["message"]}
            if d["kind"] == "accept":
                best = self.best_accept(case, threads)
                if best:
                    return best
            self.plan[sid]["dropped"] = True
            live.remove(sid)
        best = self.best_accept(case, threads)
        return best or {"supplier_id": live_threads(threads)[0], "message": {"action": {"type": "walk_away"}}}

    # ---------- learning ----------

    def after_case(self, case, threads, result, replay=None):
        """Update every supplier's persona with what happened, and the negotiation log."""
        for sid, p in self.plan.items():
            events = threads.get(sid, [])
            lessons = None
            if self.llm and len(events) > 1:
                lessons = self.llm.lessons(_transcript(case, sid, events, result))
            entry = personas.record(p["persona"], case, events, result, p["observations"], lessons, replay)
            if self.kb:
                personas.save(p["persona"])
                personas.append_negotiation(entry, sid)
            log.case(
                {
                    "case": case["case_id"],
                    "supplier": sid,
                    **{k: entry[k] for k in ("outcome", "score", "rounds", "claims", "lever_answered")},
                }
            )
        if self.kb:
            personas.write_index()


def _signature(body):
    """The last non-empty line of a supplier's e-mail: usually the company name."""
    lines = [ln.strip() for ln in (body or "").splitlines() if ln.strip()]
    return lines[-1][:80] if lines else None


def _ack(moved, lever, reading):
    if moved and lever:
        return f"They moved on the price and answered our {lever.replace('_', ' ')} option."
    if moved:
        return "They moved on the price."
    if lever:
        return f"They answered our {lever.replace('_', ' ')} option."
    if reading.get("needs_approval"):
        return "They need an approval on their side for a bigger step."
    return None


def _transcript(case, sid, events, result):
    out = [f"CASE {case.get('case_id')} {case.get('type')} goal={case['buyer'].get('category_goal')} supplier={sid}"]
    for m in events:
        who = m.get("from")
        terms = (m.get("term_sheets") or [{}])[0].get("terms", {})
        out.append(f"--- {who} status={m.get('status', '')} terms={terms}\n{(m.get('body') or '')[:1200]}")
    keep = ("deal", "supplier_id", "terms", "c_open", "c_deal", "c_best", "score")
    out.append("RESULT " + str({k: result.get(k) for k in keep}))
    return "\n".join(out)
