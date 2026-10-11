"""Numbers only: C of a sheet, what a sheet is worth to the supplier, the non-price terms we ask for
and, in relationship goals, the price below which a lower price costs us more than it saves.
Nothing here calls a model; every figure that reaches a term sheet comes from here."""

import itertools
import math

from arena_kit.cost import RELATIONSHIP_GOALS, closing_terms, complete_offer, must_haves_ok, supplier_value, total_cost


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


def deal_cost(case, terms, std, est=None):
    """The accept gate: C of a sheet with a price that keeps every must-have and is cheaper than
    the alternative (relationship charge included), else None. The C returned is the C checked."""
    if not terms.get("unit_price") or not must_haves_ok(case, terms, std):
        return None
    c = cost(case, terms, std, est)
    return c if c < c_alt(case) else None


def break_even(case, terms, std, est=None):
    """The highest price at `terms` still cheaper than the alternative (C below C_alt by a cent of
    price), or None when the case has no alternative; 0.0 when no positive price beats it. No sheet of ours goes
    above it: a deal there would be refused at the close, and an agreement freezes the supplier's
    price. C is convex in the price: the relationship charge falls as it rises (P01 at 0.0 cost
    more than its alternative, and the cap sent a 0.0 sheet), so the search starts at C's minimum."""
    ceiling = c_alt(case)
    if math.isinf(ceiling):
        return None

    def c(price):
        return cost(case, at_price(terms, price), std, est)

    lo, hi = 0.01, max(1.0, terms.get("unit_price") or 1.0) * 3
    a, b = lo, hi
    for _ in range(100):  # ternary search for the cheapest price
        m1, m2 = a + (b - a) / 3, b - (b - a) / 3
        a, b = (a, m2) if c(m1) <= c(m2) else (m1, b)
    lo = (a + b) / 2
    if not c(lo) < ceiling:
        return 0.0
    for _ in range(60):  # above the minimum, C rises with the price
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if c(mid) < ceiling else (lo, mid)
    cap = round(math.floor(lo * 100) / 100 - 0.01, 2)
    return max(0.0, cap)


def quoted_offer(case, terms, std=None):
    """An outgoing sheet with exactly the quoted effective package, never snapped terms."""
    effective = closing_terms(case, terms, std)
    if any(effective.get(k) != v for k, v in case.get("fixed_terms", {}).items()):
        return None
    offer = {k: effective.get(k) for k in case["negotiable"]}
    price = offer.get("unit_price")
    if not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
        return None
    opts = case.get("term_options", {})
    if any(opts.get(k) and v not in opts[k] for k, v in offer.items()):
        return None
    if closing_terms(case, offer, std) != effective:
        return None
    return offer if must_haves_ok(case, offer, std) else None


def known_incoterm(case, terms):
    """`terms` with an Incoterm the case prices; an unknown one (a hidden case's quote) would be a
    KeyError in the kit, so it falls back to the costliest, as `closing_terms` does for a gap."""
    freight = case["buyer"]["freight_eur_per_unit"]
    if terms.get("incoterm") in freight or "incoterm" not in terms:
        return terms
    return {**terms, "incoterm": max(freight, key=freight.get)}


def estimate(case, std, rate, full_cost=None, ppm=None, lead=None, overtime=0.0):
    """Our view of the supplier for `supplier_value` and the relationship term. `lead`: the lead
    time it quoted; `overtime`: what each day faster costs it, as a share of the price."""
    standard = known_incoterm(case, closing_terms(case, {}, known_incoterm(case, std or {})))
    est = {"standard": standard, "interest_rate": rate, "lead": lead, "overtime": overtime}
    if ppm is not None:
        est["ppm"] = ppm
    if full_cost:
        est["full_cost"] = full_cost
    est["index_moves"] = {}  # series -> its change over the last 12 months (share), what the supplier expects on
    return est


# The most a supplier is assumed to value an index clause at, as a share of the price. The model
# below is linear in the driver's move and the material share; it is backed by one supplier that
# valued its clause at 8.5 % (Nordmark, P02). Copper's 48 % year would value a 55 % share at 24 %
# of the price (P14), which nothing supports.
CLAUSE_VALUE_MAX = 0.08


def clause_share(clause, est):
    """What a clause is worth to the supplier as a share of the price: it expects its driver to
    move on as it did over the last twelve months (what it cites in its quote), and the clause
    pays it that share beyond the deadband, capped at `CLAUSE_VALUE_MAX`. None without a move."""
    move = est.get("index_moves", {}).get(clause.get("series"))
    if move is None:
        return None
    exposed = max(0.0, move - (clause.get("deadband_pct") or 0) / 100)
    return min(CLAUSE_VALUE_MAX, (clause.get("material_share") or 0) * exposed)


def clause_value(terms, est):
    """What an index clause is worth to the supplier per unit. Nordmark agreed at once to a copper
    clause 4 % below its fixed price (P02); the distributors priced the AS-14404 deadband at
    exactly our cost (P08, P18)."""
    clause = terms.get("index_clause")
    if not clause:
        return 0.0
    share = clause_share(clause, est)
    return 0.0 if share is None else share * (terms.get("unit_price") or 0)


def clause_cost_share(case, clause):
    """Our cost of a clause as a share of the spend: the case's path beyond the deadband plus the
    index risk charge."""
    b = case["buyer"]
    share, deadband = clause.get("material_share") or 0, (clause.get("deadband_pct") or 0) / 100
    path = abs(b.get("index_paths", {}).get(clause.get("series"), 0.0))
    return share * max(0.0, path - deadband) + share * b.get("index_risk_pct", 0) / 100


def clause_trade(case, est, min_gain=0.02):
    """The index clause worth trading: the supplier's value less our cost, as a share of the price,
    above `min_gain`; among equal gains the widest deadband (least risk). None when no clause pays
    (P08, P18: the supplier's value equals our cost) or the case has none to offer."""
    best = None
    for clause in case.get("term_options", {}).get("index_clause") or []:
        if not clause:
            continue
        theirs = clause_share(clause, est)
        if theirs is None:
            continue
        gain = theirs - clause_cost_share(case, clause)
        key = (round(gain, 4), clause.get("deadband_pct") or 0)
        if gain >= min_gain and (best is None or key > best[0]):
            best = (key, clause)
    return best[1] if best else None


def value(case, terms, est):
    """What a sheet is worth to the supplier per unit, in cash at its standard terms, less the
    overtime a faster delivery than it quoted costs it (fully booked suppliers: about 0.5 % of
    the price per day, P05 and P10)."""
    v = supplier_value(case, known_incoterm(case, terms), est) + clause_value(terms, est)
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


def plan_terms(case, std, est, ref_terms, ref_price):
    """The non-price terms that cost us least once the supplier prices them at its own valuation:
    for every allowed combination, the price worth the same to it as `ref_price` at `ref_terms`,
    then C at that price; among equal C, the supplier's favourite. Returns (terms with that price, C)."""
    target = value(case, {**ref_terms, "unit_price": ref_price}, est)
    rows = []
    for combo in options(case) or [{}]:
        terms = complete_offer(case, {**ref_terms, **combo, "unit_price": ref_price})
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


def at_price(terms, price):
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
        c = cost(case, at_price(terms, p), std, est)
        if c < best_c - 1e-6:
            best_p, best_c = p, c
    return round(best_p, 2)
