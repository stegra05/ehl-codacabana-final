"""Numbers: the cost C of every package, the floor and anchor per supplier, probe sheets that
trade price against the lever a supplier values, the concession schedule and the closing gate.
Nothing here calls a model; every figure that reaches a term sheet is computed here."""

import math

from arena_kit.cost import closing_terms, complete_offer, must_haves_ok, total_cost

GOAL_CAPTURE = {"leverage": 0.75, "routine": 0.5, "stabilise": 0.6, "secure_supply": 0.55, "quality_first": 0.65}
OPENING_GAP = {"strategic": 0.05, "important": 0.08, "standard": 0.12}
# Outside stabilise and secure_supply the arena charges nothing for the supplier's margin;
# this is the margin we still leave an important supplier on its estimated full cost.
TIER_MARGIN = {"strategic": 4.0, "important": 2.0, "standard": 0.0}
# Price increase: the share of the justified increase we concede in the opening sheet, by tier.
JUSTIFIED_SHARE = {"strategic": 0.5, "important": 0.25, "standard": 0.0}
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


def supplier_estimate(case, persona, std, quote_price, cost_fact=None):
    """Our estimate of the supplier for the relationship term: full cost per unit and its cost of
    money. `cost_fact`: the should-cost fact for the part (claims.ClaimBank.should_cost), if any.
    Standard terms the quote PDF did not give are filled from the case's defaults, so the
    relationship term never fails on a missing field."""
    if cost_fact and cost_fact.get("unit_cost"):
        factor = 1.0 if cost_fact.get("supplier") else persona.get("estimate", {}).get("country_factor", 1.0)
        full_cost, source = cost_fact["unit_cost"] * factor, "should_cost"
    elif quote_price:
        full_cost, source = quote_price * 0.88, "assumed"  # no should-cost: assume a 12 % margin in the quote
    else:
        return None
    return {
        "full_cost": round(full_cost, 2),
        "interest_rate": persona.get("estimate", {}).get("interest_rate", 0.08),
        "standard": closing_terms(case, {}, std),
        "source": source,
    }


def floor_price(case, persona, est, quote_price):
    """The lowest price we ever write into a sheet: the supplier's estimated full cost plus the
    margin we leave it, and never a fantasy figure far below its quote."""
    guard = persona.get("relationship", {})
    goal = case.get("buyer", {}).get("category_goal")
    if goal in ("stabilise", "secure_supply"):
        # the arena itself charges for every margin point below the sustainable margin
        margin = max(guard.get("min_margin_pct", 2.0), case["buyer"].get("sustainable_margin_pct") or 0)
    else:
        margin = TIER_MARGIN.get(persona.get("importance", {}).get("tier"), 0.0)
    if est and est.get("source") == "should_cost":
        floor = est["full_cost"] / (1 - margin / 100)
    else:  # no should-cost: below the opening gap of the tier, so the anchor is not clipped
        tier = persona.get("importance", {}).get("tier", "standard")
        floor = (quote_price or 0) * (1 - OPENING_GAP.get(tier, 0.12) - 0.03)
    if quote_price:
        ceiling = quote_price if goal in ("stabilise", "secure_supply") else quote_price * 0.97
        floor = min(max(floor, quote_price * 0.80), ceiling)
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
        share = JUSTIFIED_SHARE.get(tier, 0.0)
        anchor = current * (1 + share * max(0.0, justified_pct or 0.0) / 100)
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
        by_cost = sorted(options, key=lambda o: cost(case, {**terms, field: o}, std, est))
        best = cost(case, {**terms, field: by_cost[0]}, std, est)
        ties = [o for o in by_cost if cost(case, {**terms, field: o}, std, est) <= best + 0.01]
        # free for us: take the value the supplier likes (a lead time it need not rush for)
        terms[field] = SUPPLIER_FRIENDLY.get(field, lambda t: t[0])(ties) if len(ties) > 1 else ties[0]
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


def sheets(case, std, est, price, levers, floor, standing=None, hold=None):
    """Up to three sheets: A at `price` with our best terms, then one variant per lever that moves
    the lever to the supplier's side at the same C for us. `hold` pins fields the supplier already
    answered. Every sheet is complete, keeps the must-haves and costs less than the standing offer."""
    base = {**best_nonprice(case, std, est, price), **(hold or {})}
    a = complete_offer(case, {**base, "unit_price": price})
    c_a = cost(case, a, std, est)
    out = [a]
    for lever in levers:
        value = supplier_side(case, lever, a.get(lever))
        if lever in (hold or {}) or value is None:
            continue
        variant = {**a, lever: value}
        lo = floor if lever not in ("ppm_commitment", "chargeback_eur_per_complaint") else price
        v_price = solve_price(case, variant, std, est, c_a, lo * 0.9, max(price * 1.3, lo))
        variant = complete_offer(case, {**variant, "unit_price": max(v_price, floor * 0.97)})
        if variant not in out:
            out.append(variant)
        if len(out) >= 3:
            break
    c_std = cost(case, standing, std, est) if standing else math.inf
    keep = [s for s in out if must_haves_ok(case, s, std) and cost(case, s, std, est) < c_std]
    return keep or [a]


def concession(ours_last, theirs, round_idx, moved, close_in=False, small=False):
    """Our next price toward theirs: a falling share of the gap, only after they moved. `small`:
    the supplier needs an approval for bigger steps, so keep the step one its rep can sign."""
    if ours_last is None or theirs is None or theirs <= ours_last:
        return ours_last
    if not moved and not close_in:
        return ours_last
    step = 0.6 if close_in else STEPS[min(round_idx, len(STEPS) - 1)]
    if small:
        step = min(step, 0.15)
    return round(min(theirs, ours_last + step * (theirs - ours_last)), 2)


def target_cost(case, c_open, c_anchor, c_cap=None):
    """Where we stop pushing: the share of the opening gap the category goal asks us to capture,
    and never above `c_cap` (a price increase: C at the justified price)."""
    goal = case.get("buyer", {}).get("category_goal", "leverage")
    target = c_open - GOAL_CAPTURE.get(goal, 0.6) * (c_open - c_anchor)
    return min(target, c_cap) if c_cap is not None else target


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


def supplier_side(case, lever, ours):
    """The value of a lever on the supplier's side, or None if there is nothing to trade."""
    if lever == "unit_price" or lever not in case.get("negotiable", []):
        return None
    options = case.get("term_options", {}).get(lever)
    if lever == "index_clause":
        clauses = [o for o in options or [] if o]
        return clauses[0] if clauses and ours != clauses[0] else None
    if lever == "incoterm":
        freight = case["buyer"]["freight_eur_per_unit"]
        theirs = max(freight, key=freight.get)
        return theirs if theirs != ours else None
    if options:
        theirs = SUPPLIER_FRIENDLY.get(lever, max)(options)
        return theirs if theirs != ours else None
    return None


def lever_analysis(case, persona, std, est, price, c_open, bank_claims=(), justified=None, asked=None, rivals=0):
    """What we can trade and what we can argue, before the first move, ranked: cheap for us and
    valuable to the supplier first. Term levers carry the C they cost us; argument levers the
    reason they weigh."""
    base = best_nonprice(case, std, est, price)
    a = complete_offer(case, {**base, "unit_price": price})
    c_a = cost(case, a, std, est)
    ranked = persona.get("levers", [])
    out = []
    for lever in case.get("negotiable", []):
        theirs = supplier_side(case, lever, a.get(lever))
        if theirs is None:
            continue
        delta = cost(case, complete_offer(case, {**a, lever: theirs}), std, est) - c_a
        if not math.isfinite(delta):
            continue
        share = delta / c_open if c_open and c_open < math.inf else 0.0
        pos = ranked.index(lever) if lever in ranked else None
        value = {0: 3.0, 1: 2.0}.get(pos, 1.0 if pos is not None else 0.5)
        score = value * max(0.1, 1 - 20 * max(share, 0.0))
        why = f"{persona.get('archetype')} values it" if pos is not None and pos < 2 else "no sign they value it"
        out.append(
            {
                "kind": "term",
                "lever": lever,
                "ours": a.get(lever),
                "theirs": theirs,
                "delta_c": round(delta),
                "delta_share_pct": round(100 * share, 2),
                "value_to_them": value,
                "score": round(score, 2),
                "why": why,
            }
        )
    strong = [c for c in bank_claims if c.get("for_us")]
    if strong:
        themes = sorted({c["theme"] for c in strong})
        out.append(
            {
                "kind": "argument",
                "lever": "data",
                "score": round(min(2.0, 0.5 * len(strong)), 2),
                "why": f"{len(strong)} verified-ready arguments: {', '.join(themes)}",
            }
        )
    notice = next((c for c in bank_claims if c["kind"] == "notice" and c["for_us"]), None)
    if notice:
        out.append({"kind": "argument", "lever": "notice", "score": 3.0, "why": notice["sentence"]})
    if justified is not None and asked is not None and asked > justified:
        out.append(
            {
                "kind": "argument",
                "lever": "justified_increase",
                "score": round(min(3.0, (asked - justified) / 2), 2),
                "why": f"they ask {asked:+.1f}%, the cost drivers justify {justified:+.1f}%",
            }
        )
    alt = c_alt(case)
    if alt < c_open:
        out.append(
            {
                "kind": "argument",
                "lever": "alternative",
                "score": 3.0,
                "why": f"our alternative costs EUR {alt:,.0f} against EUR {c_open:,.0f} for the opening",
            }
        )
    if rivals:
        out.append(
            {"kind": "argument", "lever": "competition", "score": 2.5, "why": f"{rivals} other bidder(s) in this case"}
        )
    return sorted(out, key=lambda r: -r["score"])


def lever_line(r):
    """One line per lever, for logs and the plan command."""
    if r["kind"] == "term":
        return (
            f"{r['lever']}: ours {r['ours']} -> theirs {r['theirs']}, costs us EUR {r['delta_c']:,} "
            f"({r['delta_share_pct']}% of C), value to them {r['value_to_them']} -> score {r['score']} ({r['why']})"
        )
    return f"{r['lever']}: {r['why']} -> score {r['score']}"
