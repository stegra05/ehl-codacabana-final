"""Numbers: the cost C of every package, the floor and anchor per supplier, probe sheets that
trade price against the lever a supplier values, the concession schedule and the closing gate.
Nothing here calls a model; every figure that reaches a term sheet is computed here."""

import math

from arena_kit.cost import complete_offer, must_haves_ok, total_cost

GOAL_CAPTURE = {"leverage": 0.75, "routine": 0.5, "stabilise": 0.6, "secure_supply": 0.55, "quality_first": 0.65}
OPENING_GAP = {"strategic": 0.05, "important": 0.08, "standard": 0.12}
STEPS = [0.35, 0.25, 0.15, 0.10]
# Which value of a lever is a sweetener for the supplier (the probe sheet moves it there).
SUPPLIER_FRIENDLY = {
    "payment_days": min,
    "contract_months": max,
    "volume_per_year": max,
    "lead_time_days": max,
    "tooling_eur": max,
    "effective_date": min,
    "ppm_commitment": max,
    "chargeback_eur_per_complaint": min,
}


def cost(case, terms, std=None, est=None):
    try:
        return total_cost(case, terms, std, est)
    except (KeyError, TypeError, ValueError):
        return math.inf


def c_alt(case):
    alt = case.get("buyer", {}).get("alternative") or {}
    terms = alt.get("terms") or {}
    return cost(case, terms) if alt.get("kind") not in (None, "none") and terms.get("unit_price") else math.inf


def gate_ok(case, terms, std, est=None):
    """The accept gate: must-haves hold and the deal beats the alternative (when one exists)."""
    return (
        bool(terms.get("unit_price")) and must_haves_ok(case, terms, std) and cost(case, terms, std, est) < c_alt(case)
    )


def supplier_estimate(pkg, case, persona, std, quote_price):
    """Our estimate of the supplier for the relationship term: full cost per unit and its cost of money."""
    part = (case.get("parts") or [None])[0]
    n = persona["supplier_id"].split(":")[-1]
    fact, source = None, "assumed"
    if part:
        pn = part.split(":")[-1]
        facts = case.get("facts") or {}
        for ref, specific in ((f"cost:{pn}-{n}", True), (f"cost:{pn}", False)):
            f = facts.get(ref) or (pkg.lookup(ref) if pkg else None)
            if f and f.get("unit_cost"):
                fact, source = f, "should_cost" + ("" if specific else " (DE base)")
                factor = 1.0 if specific else persona.get("estimate", {}).get("country_factor", 1.0)
                full_cost = f["unit_cost"] * factor
                break
    if fact is None:
        if not quote_price:
            return None
        full_cost = quote_price * 0.88  # no should-cost: assume a 12 % margin in the quote
    return {
        "full_cost": round(full_cost, 2),
        "interest_rate": persona.get("estimate", {}).get("interest_rate", 0.08),
        "standard": std or {},
        "source": source,
    }


def floor_price(case, persona, est, quote_price):
    """The lowest price we ever write into a sheet: the supplier's estimated full cost plus the
    margin we leave it, and never a fantasy figure far below its quote."""
    guard = persona.get("relationship", {})
    margin = guard.get("min_margin_pct", 2.0)
    if case.get("buyer", {}).get("category_goal") in ("stabilise", "secure_supply"):
        margin = max(margin, case["buyer"].get("sustainable_margin_pct") or 0)
    if est and est.get("source", "").startswith("should_cost"):
        floor = est["full_cost"] / (1 - margin / 100)
    else:
        floor = (quote_price or 0) * (0.90 if not guard.get("protect") else 0.94)
    if quote_price:
        floor = min(max(floor, quote_price * 0.80), quote_price)
    return round(floor, 2)


def justified_increase_pct(bank, part):
    """Σ driver weight × the driver's 12-month change: what a price letter may legitimately ask."""
    changes = bank.driver_changes(part)
    return round(sum(w * pct for _, w, pct in changes), 2) if changes else None


def anchor_price(case, persona, floor, quote_price, justified_pct=None):
    """Round-1 price: the justified increase on the current price in a price case, else a
    deliberate gap below the quote - but never below the floor and never above the quote."""
    tier = persona.get("importance", {}).get("tier", "standard")
    goal = case.get("buyer", {}).get("category_goal")
    current = case.get("buyer", {}).get("current_unit_price")
    if case.get("type") == "price_increase" and current:
        anchor = current * (1 + max(0.0, justified_pct or 0.0) / 100)
    else:
        gap = OPENING_GAP.get(tier, 0.12)
        if goal == "routine":
            gap = min(gap, 0.06)
        anchor = quote_price * (1 - gap)
    anchor = max(floor, min(anchor, quote_price * 0.985))
    return round(anchor, 2)


def best_nonprice(case, std, est=None, price=None):
    """For every negotiable field but the price: the option that costs us least (ties: first)."""
    probe = price or case.get("buyer", {}).get("current_unit_price") or 1.0
    terms = complete_offer(case, {"unit_price": probe})
    for field in case.get("negotiable", []):
        options = case.get("term_options", {}).get(field)
        if field == "unit_price" or not options:
            continue
        terms[field] = min(options, key=lambda o: cost(case, {**terms, field: o}, std, est))
    return terms


def solve_price(case, terms, std, est, target_c, lo, hi):
    """The unit price at which `terms` cost us `target_c`: C rises with price, so bisect."""
    lo, hi = min(lo, hi), max(lo, hi)
    for _ in range(40):
        mid = (lo + hi) / 2
        if cost(case, {**terms, "unit_price": mid}, std, est) > target_c:
            hi = mid
        else:
            lo = mid
    return round(lo, 2)


def sheets(case, persona, std, est, price, levers, floor, standing=None, hold=None):
    """Up to three sheets: A at `price` with our best terms, then one variant per lever that moves
    the lever to the supplier's side at the same C for us. `hold` pins fields the supplier already
    answered. Every sheet is complete, keeps the must-haves and costs less than the standing offer."""
    base = {**best_nonprice(case, std, est, price), **(hold or {})}
    a = complete_offer(case, {**base, "unit_price": price})
    c_a = cost(case, a, std, est)
    out = [a]
    for lever in levers:
        options = case.get("term_options", {}).get(lever)
        if lever == "unit_price" or lever not in case.get("negotiable", []) or lever in (hold or {}):
            continue
        if lever == "index_clause":
            clauses = [o for o in options or [] if o]
            if not clauses:
                continue
            value = clauses[0]
        elif lever == "incoterm":
            freight = case["buyer"]["freight_eur_per_unit"]
            value = max(freight, key=freight.get)
        elif options:
            pick = SUPPLIER_FRIENDLY.get(lever, max)
            value = pick(options)
            if value == a.get(lever):
                continue
        else:
            continue
        variant = {**a, lever: value}
        lo = floor if lever not in ("ppm_commitment", "chargeback_eur_per_complaint") else price
        v_price = solve_price(case, variant, std, est, c_a, lo * 0.9, max(price * 1.3, lo))
        variant = complete_offer(case, {**variant, "unit_price": max(v_price, floor * 0.97)})
        if variant not in out:
            out.append(variant)
        if len(out) >= 3:
            break
    keep = []
    c_std = cost(case, standing, std, est) if standing else math.inf
    for s in out:
        if must_haves_ok(case, s, std) and cost(case, s, std, est) < c_std:
            keep.append(s)
    return keep or [a]


def concession(ours_last, theirs, round_idx, moved, close_in=False):
    """Our next price toward theirs: a falling share of the gap, only after they moved."""
    if ours_last is None or theirs is None or theirs <= ours_last:
        return ours_last
    if not moved and not close_in:
        return ours_last
    step = 0.6 if close_in else STEPS[min(round_idx, len(STEPS) - 1)]
    return round(min(theirs, ours_last + step * (theirs - ours_last)), 2)


def target_cost(case, c_open, c_anchor):
    """Where we stop pushing: the share of the opening gap the category goal asks us to capture."""
    goal = case.get("buyer", {}).get("category_goal", "leverage")
    return c_open - GOAL_CAPTURE.get(goal, 0.6) * (c_open - c_anchor)


def describe(case, sheet):
    """A term sheet in plain words, for the e-mail (figures exactly as in the sheet)."""
    parts = [f"EUR {sheet['unit_price']:.2f} per unit"] if sheet.get("unit_price") is not None else []
    labels = {
        "payment_days": lambda v: f"payment {v} days net",
        "contract_months": lambda v: f"{v} months" if v else "a single order",
        "volume_per_year": lambda v: f"{v:,} units a year",
        "lead_time_days": lambda v: f"lead time {v} days",
        "effective_date": lambda v: f"valid from {v}",
        "incoterm": lambda v: f"{v}" + (" Hollerau" if v == "DAP" else ""),
        "tooling_eur": lambda v: f"tooling EUR {v:,.0f}" if v else "no tooling charge",
        "ppm_commitment": lambda v: f"{v} ppm",
        "chargeback_eur_per_complaint": lambda v: f"EUR {v:,.0f} per complaint",
        "index_clause": lambda v: (
            f"price follows {v['series']} on {int(v['material_share'] * 100)}% of the price, "
            f"deadband {v['deadband_pct']}%"
            if v
            else "fixed price"
        ),
    }
    for field in case.get("negotiable", []):
        if field in labels and field in sheet:
            parts.append(labels[field](sheet[field]))
    return ", ".join(parts)
