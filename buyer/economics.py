"""Numbers only: C of a sheet, what a sheet is worth to the supplier, the non-price terms we ask for
and, in relationship goals, the price below which a lower price costs us more than it saves.
Nothing here calls a model; every figure that reaches a term sheet comes from here."""

import itertools
import math

from arena_kit.cost import closing_terms, complete_offer, must_haves_ok, supplier_value, total_cost

RELATIONSHIP_GOALS = {"stabilise", "secure_supply"}


def cost(case, terms, std=None, est=None):
    """C in EUR; infinite for sheets the cost function cannot price. The relationship charge
    needs a full-cost estimate; without one it counts as 0."""
    if est is not None and not est.get("full_cost"):
        est = None
    try:
        return total_cost(case, terms, std, est)
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return math.inf


def c_alt(case):
    alt = case["buyer"].get("alternative") or {}
    terms = alt.get("terms") or {}
    if alt.get("kind") in (None, "none") or not terms.get("unit_price"):
        return math.inf
    return cost(case, terms)


def acceptable(case, terms, std, est=None):
    """The accept gate: a price, every must-have kept, cheaper than the alternative."""
    return (
        bool(terms.get("unit_price")) and must_haves_ok(case, terms, std) and cost(case, terms, std, est) < c_alt(case)
    )


def estimate(case, std, rate, full_cost=None, ppm=None, lead=None, overtime=0.0):
    """Our view of the supplier for `supplier_value` and the relationship term. `lead`: the lead
    time it quoted; `overtime`: what each day faster costs it, as a share of the price."""
    est = {"standard": closing_terms(case, {}, std), "interest_rate": rate, "lead": lead, "overtime": overtime}
    if ppm is not None:
        est["ppm"] = ppm
    if full_cost:
        est["full_cost"] = full_cost
    return est


def value(case, terms, est):
    """What a sheet is worth to the supplier per unit, in cash at its standard terms, less the
    overtime a faster delivery than it quoted costs it (fully booked suppliers: about 0.5 % of
    the price per day, P05 and P10)."""
    v = supplier_value(case, terms, est)
    lead, quoted = terms.get("lead_time_days"), est.get("lead")
    if est.get("overtime") and lead is not None and quoted and lead < quoted:
        v -= est["overtime"] * terms["unit_price"] * (quoted - lead)
    return v


def price_for_value(case, terms, est, target):
    """The unit price at which `terms` are worth `target` to the supplier (value rises with price)."""
    lo, hi = 0.0, max(1.0, target) * 3
    for _ in range(60):
        mid = (lo + hi) / 2
        if value(case, {**terms, "unit_price": mid}, est) < target:
            lo = mid
        else:
            hi = mid
    return hi


def options(case):
    """Every combination of allowed non-price values: [{field: value}]."""
    opts = case.get("term_options") or {}
    fields = [f for f in case["negotiable"] if f != "unit_price" and opts.get(f)]
    return [dict(zip(fields, combo, strict=True)) for combo in itertools.product(*(opts[f] for f in fields))]


# Where a value costs us nothing more, the side the supplier prefers: a later delivery needs no
# overtime, a longer contract and a larger volume give it security (months beyond our horizon
# cost us nothing), a looser defect commitment and a smaller chargeback cost it less.
FRIENDLY = {
    "lead_time_days": 1,
    "contract_months": 1,
    "volume_per_year": 1,
    "ppm_commitment": 1,
    "chargeback_eur_per_complaint": -1,
    "tooling_eur": 1,
}


def friendliness(terms):
    """Higher is better for the supplier."""
    return tuple(FRIENDLY[f] * (terms.get(f) or 0) for f in FRIENDLY if f in terms)


def plan_terms(case, std, est, ref_terms, ref_price, keep=None, require_clause=False):
    """The non-price terms that cost us least once the supplier prices them at its own valuation:
    for every allowed combination, the price worth the same to it as `ref_price` at `ref_terms`,
    then C at that price; among equal C, the supplier's favourite. `keep` pins fields;
    `require_clause`: the supplier insists on an index clause. Returns (terms with that price, C)."""
    target = value(case, {**ref_terms, "unit_price": ref_price}, est)
    rows = []
    for combo in options(case) or [{}]:
        if keep and any(combo.get(k, v) != v for k, v in keep.items()):
            continue
        if require_clause and not combo.get("index_clause"):
            continue
        terms = complete_offer(case, {**ref_terms, **combo, **(keep or {}), "unit_price": ref_price})
        terms["unit_price"] = round(price_for_value(case, terms, est, target), 2)
        if not must_haves_ok(case, terms, std):
            continue
        rows.append((cost(case, terms, std, est), terms))
    if not rows:
        return None
    low = min(c for c, _ in rows)
    ties = [(c, t) for c, t in rows if c <= low + max(1.0, abs(low) * 1e-5)]
    c, terms = max(ties, key=lambda r: friendliness(r[1]))
    return terms, c


def at_price(case, terms, price):
    return {**terms, "unit_price": round(price, 2)}


def relationship_optimum(case, terms, std, est, lo, hi):
    """Relationship goals: the price in [lo, hi] with the lowest C, relationship charge included
    (C falls with price until the margin charge grows faster). Without a full-cost estimate: lo."""
    if case["buyer"].get("category_goal") not in RELATIONSHIP_GOALS or not est.get("full_cost"):
        return None
    best_p, best_c = lo, math.inf
    steps = 200
    for i in range(steps + 1):
        p = lo + (hi - lo) * i / steps
        c = cost(case, at_price(case, terms, p), std, est)
        if c < best_c - 1e-6:
            best_p, best_c = p, c
    return round(best_p, 2)
