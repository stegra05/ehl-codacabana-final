"""The demo bidding before the real one: a demo supplier bids against a demo buyer, in code and in
shares of the quote, so a whole grid of buyer strategies plays in milliseconds. The demo supplier
is the playbook the supplier subagent wrote from the research (`research.SUPPLIER`), executed the
way the arena's suppliers behaved (`docs/learnings.md`, Supplier behaviour); the demo buyer is the
policy's own price step. The strategy with the lowest demo deal price opens the real bidding."""

import statistics

# Keep the experiment narrow: at most 2 percentage points closer to the quote. A higher anchor is
# only a candidate, not a rule; the demo must predict a better deal to select it.
SHIFTS = (0.0, 0.01, 0.02)  # opening price against the policy's default, share of the quote
FRACTIONS = (0.2, 0.3)  # share of the gap we move per round
# The demo supplier, clamped: (low, high, default). Defaults are the typical practice supplier.
MODEL = {
    "floor": (0.7, 0.995, 0.9),  # the lowest price it takes, share of its quote
    "first_drop": (0.0, 0.2, 0.04),  # its round-1 concession: a cap, not a reaction to our anchor
    "step": (0.001, 0.04, 0.012),  # the most it concedes in round 2, shrinking after
    "counters": (1, 6, 4),  # counters it makes before its final offer
    "patience": (0.1, 0.6, 0.4),  # cumulative gap between our sheets and its counters it bears
}
SHRINK = 0.6  # its step cap from one round to the next
TIE = 0.003  # demo prices this close are the same: the playbook is an estimate


def blend(models):
    """One playbook from several answers of the supplier subagent (its answers vary from call to
    call): the median of each value, the majority on `eager`."""
    models = [m for m in models if m]
    if not models:
        return None
    out = {key: statistics.median_low(m[key] for m in models) for key in MODEL}
    out["eager"] = sum(m["eager"] for m in models) * 2 > len(models)
    return out


def clamp_model(raw):
    """The supplier subagent's playbook with every value in range; gaps and junk get the default."""
    raw = raw or {}
    out = {}
    for key, (lo, hi, default) in MODEL.items():
        try:
            out[key] = min(hi, max(lo, type(default)(raw.get(key, default))))
        except (TypeError, ValueError):
            out[key] = default
    out["eager"] = raw.get("eager") is True  # concedes its step whatever we move (job shops with idle machines)
    return out


def bid(step, model, anchor, fraction, budget, rounds=10):
    """One demo negotiation: (deal price as a share of the quote, how it ended)."""
    theirs = prev = 1.0
    ours, used = [], 0.0
    for n in range(rounds):
        if n == 0:
            price = anchor
        else:
            conceded = (prev - theirs) / prev if n == 1 else 0.0
            price = step(ours[-1], theirs, conceded, n == 1, fraction, budget, used)
        move = price - ours[-1] if ours else 0.0
        ours.append(price)
        used += max(0.0, (theirs - price) / theirs)
        if n == 0:
            want = 1.0 - model["first_drop"]
        else:
            cap = model["step"] * SHRINK ** (n - 1)
            want = theirs - (cap if model["eager"] else min(0.8 * move, cap))
        want = max(model["floor"], want)
        if price >= want:
            return price, "agreed"  # it agrees the moment our sheet reaches the counter it would make
        prev, theirs = theirs, want
        if n + 1 >= model["counters"] or used > model["patience"]:
            return theirs, "final_offer"
    return theirs, "round_limit"


def tune(step, model, ratio, budget, proposal=None, low=0.0, high=1.0):
    """The opening ratio and the fraction with the lowest demo deal price, among the grid around the
    policy's default `ratio` and lead researcher's proposal. Ties go to the default to limit noise.
    Returns (ratio, fraction, [(ratio, fraction, price, end)])."""
    grid = [(d, f) for d in SHIFTS for f in FRACTIONS]
    if proposal and proposal not in grid:
        grid.append(proposal)
    rows = []
    for shift, fraction in grid:
        anchor = round(min(high, max(low, ratio + shift)), 4)
        price, end = bid(step, model, anchor, fraction, budget)
        rows.append((anchor, fraction, round(price, 4), end))
    low_price = min(r[2] for r in rows)
    near = [r for r in rows if r[2] <= low_price + TIE]
    best = min(near, key=lambda r: (abs(r[0] - ratio), abs(r[1] - 0.3), r[2]))
    return best[0], best[1], rows
