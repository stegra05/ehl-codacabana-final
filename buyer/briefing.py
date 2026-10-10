"""The preparation agent: before the first move it reads the case and the data package and writes
a briefing the policy and the writer take as input. Code only, no model: every figure in it is
computed, so it is recomputed for every run and never stale.

Per case: the constraints (negotiable fields, options, fixed terms, must-haves, rounds), the
economics (need, horizon, the alternative and its C), the market (other quotes and prices for the
part, the part's cost drivers with their index path, should-cost rows, the supplier's negotiation
record). Per supplier: its importance to us (sourcing, tooling, spend, class), the C floor as our
reference (the cheapest allowed terms at the price that still leaves the supplier its margin), and
the plan variables the design's fallback constants stood for, calculated from the data:

| Variable | From |
|---|---|
| floor price | full cost (own-plant should-cost, else a country-adjusted estimate, else a share of
  the quote) plus the tier margin, or the case's sustainable margin in relationship goals |
| C floor | C of the cheapest allowed terms at the floor price, valued as the supplier values them |
| capture | share of the room from C_open to the C floor to reach before closing: by goal, more for
  a supplier that usually moves, less for one that is frozen, booked or near its cost |
| opening gap | by goal and tier, never below a binding floor; in a price increase at most the
  current price plus the tier's share of the index-justified increase |
| step | not a constant: `policy.pace` sizes every move from the rounds the clock and the round
  limit leave |

After the run, `assess` compares the C floor with the C_best the arena reveals, so the estimate
is checked on every session (`logs/runs/`)."""

import logging
import math
import statistics

from . import economics as eco
from .claims import months_back

log = logging.getLogger("buyer")

TIERS = ("standard", "important", "strategic")
# Margin left above the supplier's full cost when setting its floor, by tier (relationship goals
# take the case's sustainable margin instead).
TIER_MARGIN = {"strategic": 0.04, "important": 0.02, "standard": 0.0}
# Share of the room (C_open down to the C floor) to reach before closing, by goal.
GOAL_CAPTURE = {"leverage": 0.75, "quality_first": 0.65, "stabilise": 0.6, "secure_supply": 0.55, "routine": 0.5}
# How far below its quote the first sheet opens at most, by tier (a share of the quote). Only the
# strategic gap is tighter than the goal anchors the practice runs measured (`policy.ANCHOR`): a
# milder opening bought nothing from important suppliers and cost patience (P07, P18).
TIER_GAP = {"strategic": 0.10, "important": 0.25, "standard": 0.25}
FLOOR_BINDS = 0.95  # a floor above this share of the quote is a reference, not a bound
TARGET_BELOW_QUOTE = 0.98  # a capture target closer to its quote than this is no target
# In a price increase: the share of the index-justified increase we concede in round 1.
JUSTIFIED_SHARE = {"strategic": 0.5, "important": 0.25, "standard": 0.0}
# Full cost in other countries relative to the German cost base (data/package/company.md).
COUNTRY_FACTOR = {"AT": 1.05, "CH": 1.05, "CZ": 0.82, "PL": 0.82, "HU": 0.82, "TR": 0.75, "CN": 0.7}
QUOTE_FLOOR = 0.8  # without any cost estimate: the floor as a share of the quote (low confidence)
SPEND_SHARE_IMPORTANT, SPEND_SHARE_STRATEGIC = 0.02, 0.05


def q(pkg, sql, params=()):
    if pkg is None:
        return []
    try:
        return pkg.query(sql, params)
    except Exception:  # noqa: BLE001 - no SQLite, or a table the package lacks: the briefing goes on
        return []


def per_piece(row, key="price"):
    try:
        unit = int(row.get("price_unit") or 1) or 1
    except (TypeError, ValueError):
        unit = 1
    return row[key] / unit if row.get(key) is not None else None


# -- importance ---------------------------------------------------------------------------------
def importance(pkg, case, sid):
    """How much this supplier matters to us: {tier, score, why}. Evidence from the package
    (sourcing, tooling, class, spend) and the case (no fallback)."""
    score, why = 0, []
    if not (case["buyer"].get("alternative") or {}).get("terms", {}).get("unit_price"):
        score, why = score + 1, why + ["no fallback in this case"]
    if pkg is None or not pkg.lookup(sid):
        return {"tier": tier(score), "score": score, "why": why}
    for part in case.get("parts") or []:
        active = q(
            pkg,
            "SELECT supplier_id, quota_pct, tooling_owner FROM sourcing WHERE part_id = ? AND status = 'active'",
            (part,),
        )
        own = [r for r in active if r["supplier_id"] == sid]
        if own and len(active) == 1:
            score, why = score + 2, why + ["our only active source for this part"]
        elif own and (own[0].get("quota_pct") or 0) >= 70:
            score, why = score + 1, why + ["carries most of our volume for this part"]
        if own and own[0].get("tooling_owner") == "supplier":
            score, why = score + 1, why + ["owns the tooling"]
    sup = q(pkg, "SELECT abc_class FROM suppliers WHERE id = ?", (sid,))
    if sup and sup[0].get("abc_class") == "A":
        score, why = score + 1, why + ["an A-class supplier"]
    share = spend_share(pkg, sid)
    if share >= SPEND_SHARE_STRATEGIC:
        score, why = score + 2, why + ["a very large share of our spend"]
    elif share >= SPEND_SHARE_IMPORTANT:
        score, why = score + 1, why + ["a large share of our spend"]
    return {"tier": tier(score), "score": score, "why": why, "spend_share": round(share, 4)}


def tier(score):
    return "strategic" if score >= 4 else "important" if score >= 2 else "standard"


def spend_share(pkg, sid):
    rows = q(
        pkg,
        "SELECT supplier_id, sum(spend_eur) AS spend FROM spend_cube "
        "WHERE fiscal_year = (SELECT max(fiscal_year) FROM spend_cube) GROUP BY supplier_id",
    )
    total = sum(r["spend"] or 0 for r in rows)
    own = next((r["spend"] for r in rows if r["supplier_id"] == sid), 0) or 0
    return own / total if total else 0.0


# -- market ---------------------------------------------------------------------------------------
def market(pkg, bank, case):
    """What the data says about the part's price: other quotes, current prices, cost drivers with
    their index path, should-cost rows. Per part."""
    out = {}
    for part in case.get("parts") or []:
        quotes = [
            {**r, "unit_price": per_piece(r, "unit_price")}
            for r in q(
                pkg,
                "SELECT id, supplier_id, quote_date, unit_price, price_unit, lead_time_days, payment_days "
                "FROM quotes WHERE part_id = ? ORDER BY quote_date DESC LIMIT 8",
                (part,),
            )
        ]
        prices = [
            {**r, "price": per_piece(r)}
            for r in q(
                pkg,
                "SELECT supplier_id, valid_from, price, price_unit FROM price_conditions WHERE part_id = ? "
                "ORDER BY valid_from DESC LIMIT 6",
                (part,),
            )
        ]
        costs = q(
            pkg,
            "SELECT id, supplier_id, cost_base, unit_cost, price_unit, material_eur, conversion_eur, overhead_eur, "
            "confidence_pct FROM should_cost WHERE part_id = ? ORDER BY estimate_date DESC",
            (part,),
        )
        out[part] = {
            "quotes": quotes,
            "prices": prices,
            "should_cost": [{**r, "unit_cost": per_piece(r, "unit_cost")} for r in costs],
            "drivers": drivers(pkg, bank, part),
        }
    return out


def drivers(pkg, bank, part, since=None):
    """The part's cost drivers: weight and index change over 12 months (or since `since`)."""
    out = []
    for r in q(pkg, "SELECT series_id, weight FROM cost_drivers WHERE part_id = ?", (part,)):
        ids = bank.ids(f"idx:{r['series_id']}@")
        if not ids:
            continue
        last = ids[-1].split("@")[-1]
        base = since if since and since <= last else months_back(last, 12)
        a, b = bank.fact(f"idx:{r['series_id']}@{base}"), bank.fact(ids[-1])
        if not a or not b or not a.get("value"):
            continue
        change = b["value"] / a["value"] - 1
        out.append(
            {"series": r["series_id"], "weight": r["weight"], "from": base, "to": last, "change": round(change, 4)}
        )
    return out


def justified_increase(pkg, bank, case, sid):
    """A price-increase case: the increase the part's cost drivers justify since its last price
    change (index-weighted), against what the letter asks. None when the data has no drivers."""
    parts = case.get("parts") or []
    if case.get("type") != "price_increase" or len(parts) != 1:
        return None
    rows = q(
        pkg,
        "SELECT valid_from FROM price_conditions WHERE part_id = ? AND supplier_id = ? "
        "ORDER BY valid_from DESC LIMIT 1",
        (parts[0], sid),
    )
    since = rows[0]["valid_from"][:7] if rows and rows[0].get("valid_from") else None
    d = drivers(pkg, bank, parts[0], since)
    if not d:
        return None
    justified = sum(x["weight"] * x["change"] for x in d)
    doc = bank.fact(case.get("trigger_doc") or "") or {}
    asked = doc.get("asked_pct")
    return {"justified_pct": round(100 * justified, 2), "asked_pct": asked, "since": since, "drivers": d}


def record(pkg, sid):
    """How this supplier settled past negotiations with us: asked against settled, in %."""
    rows = q(pkg, "SELECT asked_pct, settled_pct FROM negotiation_history WHERE supplier_id = ?", (sid,))
    rows = [r for r in rows if r.get("asked_pct") is not None and r.get("settled_pct") is not None]
    if not rows:
        return None
    return {
        "events": len(rows),
        "asked_pct": round(statistics.mean(r["asked_pct"] for r in rows), 2),
        "settled_pct": round(statistics.mean(r["settled_pct"] for r in rows), 2),
        "moved_pct": round(statistics.mean(r["asked_pct"] - r["settled_pct"] for r in rows), 2),
    }


def payment_record(pkg, sid):
    """How we pay it: days late on average over its last invoices (a lever it values)."""
    rows = q(
        pkg,
        "SELECT julianday(paid_date) - julianday(due_date) AS late FROM invoices "
        "WHERE supplier_id = ? AND paid_date IS NOT NULL ORDER BY invoice_date DESC LIMIT 40",
        (sid,),
    )
    late = [r["late"] for r in rows if r.get("late") is not None]
    return round(statistics.mean(late), 1) if late else None


# -- the case brief -----------------------------------------------------------------------------
def prepare(case, pkg, bank):
    b = case["buyer"]
    c_alt = eco.c_alt(case)
    return {
        "constraints": {
            "negotiable": case["negotiable"],
            "options": case.get("term_options") or {},
            "fixed": case.get("fixed_terms") or {},
            "must_haves": b.get("must_haves") or [],
            "round_limit": case.get("round_limit", 10),
        },
        "economics": {
            "goal": b.get("category_goal"),
            "type": case.get("type"),
            "need_per_year": b["need_per_year"],
            "horizon_years": b["horizon_years"],
            "current_unit_price": b.get("current_unit_price"),
            "fallback_unit_price": b.get("fallback_unit_price"),
            "alternative": (b.get("alternative") or {}).get("kind"),
            "c_alt": None if math.isinf(c_alt) else c_alt,
        },
        "market": market(pkg, bank, case),
    }


# -- the supplier brief -------------------------------------------------------------------------
def plausible(row, q_price):
    """A should-cost figure in the quote's range: as recorded, else per piece where the row is
    priced per 100 or 1000 (P14's row says 304 per 100 against a quote of 316 per piece), else
    None."""
    for cost in (row.get("unit_cost"), per_piece(row, "unit_cost")):
        if cost and q_price and 0.3 * q_price <= cost <= 1.3 * q_price:
            return cost
    return None


def full_cost(pkg, bank, case, sid, prof, q_price):
    """(full cost per unit, confidence): own-plant should-cost (high), a generic estimate scaled
    to the supplier's country (medium), else a share of its quote (low). A bundle has none: one
    component's cost is not the price unit of the kit."""
    parts = case.get("parts") or []
    if len(parts) != 1:
        return q_price * QUOTE_FLOOR, "low"
    rows = q(pkg, "SELECT supplier_id, unit_cost, price_unit FROM should_cost WHERE part_id = ?", (parts[0],))
    for ref in bank.ids("cost:"):  # the case's own facts (no table rows)
        f = bank.fact(ref)
        if f and f.get("part") == parts[0] and f.get("unit_cost"):
            rows.append(
                {"supplier_id": f.get("supplier"), "unit_cost": f["unit_cost"], "price_unit": f.get("price_unit")}
            )
    own = [c for r in rows if r.get("supplier_id") == sid and (c := plausible(r, q_price))]
    if own:
        return own[0], "high"
    generic = [c for r in rows if not r.get("supplier_id") and (c := plausible(r, q_price))]
    if generic:
        return generic[0] * COUNTRY_FACTOR.get(prof.get("country") or "DE", 1.0), "medium"
    return q_price * QUOTE_FLOOR, "low"


def margin_for(case, tier_):
    b = case["buyer"]
    if b.get("category_goal") in eco.RELATIONSHIP_GOALS and b.get("sustainable_margin_pct"):
        return b["sustainable_margin_pct"] / 100
    return TIER_MARGIN[tier_]


def capture_for(case, prof, rec, near_cost):
    """Share of the room to reach before closing: the goal's base, more for a supplier that
    usually moves, less for one that will not (frozen, booked, approval ladder, near its cost)."""
    c = GOAL_CAPTURE.get(case["buyer"].get("category_goal"), 0.6)
    why = [f"goal base {c}"]
    if rec and rec["moved_pct"] >= 2:
        c, why = c + 0.1, why + ["usually moves in a negotiation"]
    rigid = {"price_frozen", "capacity_full", "approval_2pct"} & set(prof.get("signals") or [])
    if rigid:
        c, why = c - 0.1, why + [f"rigid: {', '.join(sorted(rigid))}"]
    if near_cost:
        c, why = c - 0.15, why + ["sells near our cost estimate"]
    return round(min(0.9, max(0.4, c)), 2), why


def price_for_cost(case, terms, std, est, target_c, lo, hi):
    """The price at `terms` where C equals `target_c` (C rises with price), within [lo, hi]."""
    if eco.cost(case, eco.at_price(case, terms, lo), std, est) >= target_c:
        return lo
    for _ in range(50):
        mid = (lo + hi) / 2
        if eco.cost(case, eco.at_price(case, terms, mid), std, est) < target_c:
            lo = mid
        else:
            hi = mid
    return round(hi, 2)


def plan(case, pkg, bank, sid, quote, std, est, prof, terms, quote_at_terms, stance=None):
    """The supplier's plan variables from the data (see the module docstring). `terms`: the
    non-price terms the policy asks for; `quote_at_terms`: its quote as a price at those terms;
    `stance`: the preparation agent's clamped proposal (`prep.run`), applied inside its bands."""
    q_price = quote["unit_price"]
    stance = stance or {}
    imp = importance(pkg, case, sid)
    cost, confidence = full_cost(pkg, bank, case, sid, prof, q_price)
    near_cost = confidence == "high" and cost >= 0.98 * q_price
    margin = margin_for(case, imp["tier"])

    def at_terms(p):  # a price at the quote's terms as the price at our terms worth the same to it
        return round(eco.price_for_value(case, terms, est, eco.value(case, eco.at_price(case, quote, p), est)), 2)

    # the floor as a price at our terms: a sheet worth full cost plus margin to the supplier. A
    # floor within 5 % of its quote (or above it) says our estimate is off, not that it quotes
    # below cost (P01, P02, P17 sell below our should-cost): then it is a reference only.
    floor = round(eco.price_for_value(case, terms, est, cost * (1 + margin)), 2)
    floor = min(floor, quote_at_terms)
    binding = confidence != "low" and floor <= FLOOR_BINDS * quote_at_terms
    planned = eco.plan_terms(case, std, est, quote, floor) if floor > 0 else None
    floor_terms = planned[0] if planned else eco.at_price(case, terms, floor)
    c_floor = eco.cost(case, floor_terms, std, est)
    c_open = eco.cost(case, quote, std, est)
    rec = record(pkg, sid)
    capture, capture_why = capture_for(case, prof, rec, near_cost)
    if stance.get("capture_delta"):
        capture = round(min(0.9, max(0.4, capture + stance["capture_delta"])), 2)
        capture_why.append(f"prep agent {stance['capture_delta']:+.2f}")
    # the room is measured along our path: its quote at our terms down to the floor at our terms
    # (at its own terms C_open may carry uncovered need or payment days our terms remove, P10)
    c_start = eco.cost(case, eco.at_price(case, terms, quote_at_terms), std, est)
    room = max(0.0, c_start - c_floor)
    target_c = c_start - capture * room
    target = price_for_cost(case, terms, std, est, target_c, floor, quote_at_terms) if binding and room > 0 else None
    if target is not None and target > TARGET_BELOW_QUOTE * quote_at_terms:
        target = None  # no room to speak of: never close in round 1 at its price
    # the deepest opening: the tier's gap below its quote, never below a binding floor
    gap = min(0.3, max(0.03, TIER_GAP[imp["tier"]] + (stance.get("opening_gap_delta") or 0.0)))
    opening_min = at_terms(q_price * (1 - gap))
    if binding:
        opening_min = max(opening_min, floor)
    # the highest opening: in a price increase today's price plus the tier's share of what the
    # cost drivers justify (letters overshoot: P01 asked 9.5 % against 2.3 % justified)
    justified = justified_increase(pkg, bank, case, sid)
    current = case["buyer"].get("current_unit_price")
    opening_max = None
    if case.get("type") == "price_increase" and current:
        allowed = max(0.0, (justified or {}).get("justified_pct") or 0.0) / 100
        opening_max = at_terms(min(q_price, current * (1 + JUSTIFIED_SHARE[imp["tier"]] * allowed)))
    return {
        "importance": imp,
        "full_cost": round(cost, 4),
        "cost_confidence": confidence,
        "near_cost": near_cost,
        "margin": margin,
        "floor": floor,
        "floor_binding": binding,
        "floor_terms": {k: v for k, v in floor_terms.items() if k != "unit_price"},
        "c_open": c_open,
        "c_start": c_start,
        "c_floor": c_floor,
        "room": round(room, 2),
        "capture": capture,
        "capture_why": capture_why,
        "target_c": round(target_c, 2),
        "target": target,
        "opening_gap": round(gap, 3),
        "opening_min": opening_min,
        "opening_max": opening_max,
        "stance": stance,
        "justified": justified,
        "record": rec,
        "we_pay_late_days": payment_record(pkg, sid),
        "levers": levers(case, quote, std, est),
    }


def levers(case, quote, std, est):
    """What each allowed value of each negotiable term is worth to us at the quote's price:
    C minus C_open, so a negative figure saves."""
    c_open = eco.cost(case, quote, std, est)
    out = {}
    opts = case.get("term_options") or {}
    for field in case["negotiable"]:
        if field == "unit_price" or not opts.get(field):
            continue
        out[field] = {}
        for v in opts[field]:
            c = eco.cost(case, {**quote, field: v}, std, est)
            out[field][repr(v)] = None if math.isinf(c) else round(c - c_open, 2)
    return out


def relationship_line(imp):
    """One sentence for the writer's brief: who this supplier is to us, in words."""
    if not imp or imp["tier"] == "standard" or not imp.get("why"):
        return None
    head = "a strategic partner" if imp["tier"] == "strategic" else "an important supplier"
    return f"{head} for us: {', '.join(imp['why'])}"


def assess(brief_by_sid, result):
    """After the run: the C floor against the C_best the arena reveals, per supplier."""
    c_best = (result or {}).get("c_best")
    if c_best is None:
        return None
    out = {}
    for sid, p in brief_by_sid.items():
        if not p or p.get("c_floor") is None or math.isinf(p["c_floor"]):
            continue
        err = (p["c_floor"] - c_best) / c_best if c_best else None
        out[sid] = {
            "c_floor": p["c_floor"],
            "c_best": c_best,
            "floor_error_pct": round(100 * err, 2) if err is not None else None,
            "cost_confidence": p["cost_confidence"],
            "c_deal": (result or {}).get("c_deal"),
            "captured": round((p["c_start"] - result["c_deal"]) / p["room"], 3)
            if result.get("c_deal") is not None and p.get("room") and p.get("floor_binding")
            else None,
        }
    return out
