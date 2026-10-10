"""One move in one supplier thread: read the reply, apply the policy (status, concessions,
levers, claims), word the e-mail, guard it. Policies are layered: hard guardrails always win, the
category goal sets the stance, the case type the playbook, the persona the lever and tone."""

import logging
import math
import re
import time

from arena_kit.docs import standard_terms
from arena_kit.play import ENDED, latest, moves_left, standing

from . import claims, economics, guard, log, personas

logger = logging.getLogger("buyer")

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
GOAL_WORDS = {
    "leverage": "leverage: the best total cost, firm and factual",
    "routine": "routine: a fair deal quickly, no long fight",
    "stabilise": "stabilise: keep this strategic supplier healthy, trade security rather than squeeze price",
    "secure_supply": "secure supply: cover the full need and protect lead time, never risk the relationship",
    "quality_first": "quality first: a ppm commitment and chargebacks matter more than the last euro",
}


def decide(agent, case, threads, sid):
    """{"kind": "send", "message": ...} | {"kind": "accept"} | {"kind": "wait"} | {"kind": "drop"}."""
    p = agent.plan[sid]
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

    reading = read(agent, p, last)
    p["dropped"] |= set(reading.get("rejected_themes") or [])
    p["themes"] = list(dict.fromkeys((reading.get("cost_driver_themes") or []) + p["themes"]))
    for field in reading.get("interested_in") or []:
        if field in p["levers"]:
            p["levers"].remove(field)
            p["levers"].insert(0, field)
    if p["rounds"] and len(p["rounds"]) == 1 and personas.refine(persona, last.get("body", ""), reading):
        logger.info("%s/%s: re-classified as %s from the first reply", case["case_id"], sid, persona["archetype"])
    prev = p["rounds"][-1] if p["rounds"] else None
    moved = bool(prev and prev["theirs"] is not None and t_price is not None and t_price < prev["theirs"] - 0.005)
    if prev and prev["sheets"] and len(prev["sheets"]) > 1:
        answered = personas.lever_answered(prev["sheets"], theirs)
        if answered:
            lever = next((k for k in answered if k != "unit_price" and answered[k] != prev["sheets"][0].get(k)), None)
            if lever:
                p["hold"][lever] = theirs.get(lever, answered[lever])
                p["lever_answered"] = lever
    gate = economics.gate_ok(case, theirs, std, est) if sheet_id else False
    left = moves_left(case, events)
    near = c_theirs <= p["target"] + 0.25 * max(0.0, p["c_open"] - p["target"])
    p["reading"] = reading

    # Reply status: agreed accepts after the gate; the round limit accepts what passes the gate.
    if status == "agreed":
        return {"kind": "accept"} if gate else {"kind": "drop", "why": "agreed terms fail the gate"}
    if sheet_id and gate and c_theirs <= p["target"] and not (moved and left > 2 and len(p["rounds"]) < 4):
        return {"kind": "accept"}  # at the target; while it still moves, one more round first
    if left <= 0:
        return {"kind": "accept"} if gate else {"kind": "drop", "why": "round limit, gate fails"}
    review_move = None
    if sheet_id and gate and stalled(p, status, moved, left, reading):
        verdict = review(case, p, sid, status, c_theirs, left)
        if verdict["decision"] == "accept":
            return {"kind": "accept"}
        review_move = verdict.get("next_move")
    # A final offer, or a reply that reads like one: no price push, at most one non-price package.
    if status == "final_offer" or (reading.get("walk_risk") == "high" and gate and p["rounds"]):
        if gate and (rel["protect"] or p["final_packages"] >= 1 or left <= 1 or near):
            return {"kind": "accept"}
        if p["final_packages"] >= 1:
            return {"kind": "accept"} if gate else {"kind": "drop", "why": "final offer fails the gate"}
        p["final_packages"] += 1
        sheets = economics.sheets(case, std, est, t_price, p["levers"], p["floor"], standing=theirs, hold=p["hold"])
        if all(economics.cost(case, s, std, est) >= c_theirs for s in sheets):
            return {"kind": "accept"} if gate else {"kind": "drop", "why": "no package beats the final offer"}
        move = (
            "They sent their final offer. We do not push the price: we accept their price level "
            "and ask for one package on the other terms."
        )
        return send(agent, case, threads, sid, p, sheets, status, reading, moved, move, t0, n_claims=1, question=None)

    round_idx = len(p["rounds"])
    if round_idx == 0:
        price = p["anchor"]
        move = (
            "Our opening: the first package is our anchor; the others trade the price against terms "
            "the supplier may value."
        )
    else:
        close_in = p["price_pushes"] >= rel["max_price_pushes"] or left <= 1 or review_move == "best_and_final"
        price = economics.concession(
            prev["price"], t_price, round_idx - 1, moved, close_in, small=bool(reading.get("needs_approval"))
        )
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
    sheets = economics.sheets(case, std, est, price, p["levers"], p["floor"], standing=theirs, hold=p["hold"])
    if sheet_id and gate and all(economics.cost(case, s, std, est) >= c_theirs for s in sheets):
        return {"kind": "accept"}
    if price < (t_price or math.inf):
        p["price_pushes"] += 1
    q = question(case, p, round_idx, reading)
    return send(
        agent,
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
        question=q,
    )


def send(agent, case, threads, sid, p, sheets, status, reading, moved, move, t0, n_claims, question):
    persona = p["persona"]
    picked = claims.ClaimBank.pick(p["claims"], p["used_ids"] | agent.used_ids, p["themes"], p["dropped"], n=n_claims)
    # RFQ: the best rival's offer, cited only after this bidder's first reply, only when cheaper.
    if (
        p["rounds"]
        and len(case.get("suppliers", [])) > 1
        and persona["relationship"].get("cite_rivals")
        and len(picked) < 3
    ):
        rivals = [c for c in agent.bank.rival_claims(sid, threads) if not any(i in p["used_ids"] for i in c["ids"])]
        if rivals:
            picked.append(min(rivals, key=lambda c: c["figure"]))
    ids = {i for c in picked for i in c["ids"]}
    sheets_text = [economics.describe(case, s) for s in sheets]
    ack = acknowledge(moved, p.get("lever_answered"), reading)
    tone = "warm" if reading.get("mood") in ("cool", "irritated") and persona["tone"] != "firm" else persona["tone"]
    body, used_llm = None, False
    if agent.llm:
        draft = agent.llm.write_email(
            brief(case, p, latest(threads[sid]), status, reading, sheets_text, picked, question, move, ack, tone)
        )
        body = guard.check(draft, ids, sheets, picked) if draft else None
        used_llm = body is not None
    if not body:
        body = guard.template(persona["name"], sheets_text, picked, question, ack, opening=not p["rounds"], tone=tone)
    latency = round(time.monotonic() - t0, 1)
    p["rounds"].append(
        {
            "price": sheets[0].get("unit_price"),
            "theirs": standing(threads[sid])[1].get("unit_price"),
            "status": status,
            "moved": moved,
            "sheets": sheets,
            "claims": [c["ids"] for c in picked],
            "latency_s": latency,
            "llm": used_llm,
        }
    )
    p["used_ids"] |= ids
    with agent.lock:
        agent.used_ids |= {i for i in ids if not i.startswith("offer:")}
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
            "latency_s": latency,
            "mood": reading.get("mood"),
            "themes": p["themes"],
        }
    )
    if latency > 40:
        logger.warning("%s/%s: decision took %.1fs", case["case_id"], sid, latency)
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


# ---------- the closer: a rule when a thread stalls ----------


def stalled(p, status, moved, left, reading):
    """Two rounds without movement, a final offer, a high walk risk, or the last two messages."""
    if len(p["rounds"]) < 2:
        return False
    if status == "final_offer" or reading.get("walk_risk") == "high" or left <= 2:
        return True
    return not moved and not p["rounds"][-1]["moved"]


def review(case, p, sid, status, c_theirs, left):
    """Accept a stalled thread once most of the target gap is captured or time is short."""
    gap = p["c_open"] - p["target"]
    captured = (p["c_open"] - c_theirs) / gap if gap > 0 else 1.0
    verdict = {
        "decision": "accept" if captured >= 0.75 or left <= 1 else "continue",
        "next_move": "best_and_final" if left <= 2 else "hold",
        "reason": f"stalled with {captured:.0%} of the target gap captured, {left} messages left",
    }
    logger.info("%s/%s: closer says %s: %s", case["case_id"], sid, verdict["decision"], verdict["reason"])
    return verdict


# ---------- reading and writing ----------


def read(agent, p, msg):
    body = msg.get("body", "") or ""
    if agent.llm:
        out = agent.llm.read_reply(p["persona"]["name"], body, msg.get("status"), msg.get("claim_results"))
        if out:
            return out
    rejected = set()
    if REJECT.search(body) and p["rounds"]:
        rejected = {c["theme"] for c in p["claims"] if any(i in p["used_ids"] for i in c["ids"])}
    return {
        "summary": body.strip().replace("\n", " ")[:200],
        "cost_driver_themes": claims.themes_in(body),
        "interested_in": [f for f, rx in INTEREST.items() if rx.search(body)],
        "rejected_themes": sorted(rejected),
        "needs_approval": bool(APPROVAL.search(body)),
        "mood": "cool" if COOL.search(body) else "neutral",
        "walk_risk": "high" if msg.get("status") == "final_offer" else "low",
        "offers_document": "",
        "cheaper_variant": "",
    }


def question(case, p, round_idx, reading):
    offered = (reading.get("offers_document") or "").lower()
    kind = case.get("type")
    if reading.get("cheaper_variant") and not p.get("asked_variant"):
        p["asked_variant"] = True
        return "Could you quote the cheaper variant you mentioned, with its price and lead time?"
    if round_idx == 0:
        if kind == "quality" or case["buyer"].get("category_goal") == "quality_first":
            return None if "8d" in offered else "Could you send us the 8D report for the open complaints?"
        if kind == "capacity":
            return None if "schedule" in offered else "Could you send us your delivery schedule for the coming months?"
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


def acknowledge(moved, lever, reading):
    if moved and lever:
        return f"They moved on the price and answered our {lever.replace('_', ' ')} option."
    if moved:
        return "They moved on the price."
    if lever:
        return f"They answered our {lever.replace('_', ' ')} option."
    if reading.get("needs_approval"):
        return "They need an approval on their side for a bigger step."
    return None


def brief(case, p, last, status, reading, sheets_text, picked, question, move, ack, tone):
    persona = p["persona"]
    arch = personas.ARCHETYPES.get(persona["archetype"], {})
    lines = [
        f"TONE: {tone}",
        f"SUPPLIER: {persona['name']} ({persona.get('country') or 'country unknown'}; "
        f"{persona['importance']['tier']} supplier; {arch.get('about', '')}).",
        f"AVOID: {', '.join(persona.get('avoid') or []) or 'nothing special'}.",
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
