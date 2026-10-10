"""The clause trade and the relationship target on a supplier the package does not know: a hedged
supplier gets no clause, an extreme index move is capped at what one supplier was seen to value a
clause at, and a supplier selling at our cost estimate still gets a relationship target."""

import copy

from arena_kit.sim import load_cases

from buyer import economics as eco
from buyer.policy import Negotiator

CLAUSE = {"series": "raw", "material_share": 0.55, "deadband_pct": 5, "base_month": "2026-08"}


def stabilise_case():
    case = copy.deepcopy(load_cases()["case:S01"])
    case["case_id"] = "case:unseen"
    case["suppliers"] = ["sup:unseen"]
    case["negotiable"].append("index_clause")
    case["fixed_terms"].pop("index_clause")
    case["term_options"]["index_clause"] = [None, CLAUSE]
    case["buyer"].update(
        category_goal="stabilise", sustainable_margin_pct=4, index_paths={"raw": 0.05}, index_risk_pct=4
    )
    return case


def opened(case, neg, move, full_cost=None, signals=()):
    terms = eco.complete_offer(case, {"unit_price": 15, "payment_days": 30})
    event = {"from": "supplier", "status": "open", "body": "", "term_sheets": [{"terms": terms, "term_sheet_id": "q"}]}
    neg.bank.move12 = lambda series: move
    neg.full_cost = lambda part, sid: (full_cost, full_cost is not None)
    from buyer import policy

    neutral = policy.profile(None, "sup:unseen")
    neutral["signals"] = sorted(signals)
    policy_profile = policy.profile
    policy.profile = lambda pkg, sid: dict(neutral)
    try:
        return neg.setup("sup:unseen", [event])
    finally:
        policy.profile = policy_profile


def test_hedged_supplier_gets_no_clause():
    case = stabilise_case()
    s = opened(case, Negotiator(case), move=0.48, signals=["hedged"])
    assert not s.terms.get("index_clause")
    assert not any(n["what"] == "clause_trade" for n in Negotiator(case).notes)


def test_clause_value_is_capped():
    est = {"index_moves": {"raw": 0.48}}
    assert eco.clause_share(CLAUSE, est) == eco.CLAUSE_VALUE_MAX
    assert eco.clause_value({"index_clause": CLAUSE, "unit_price": 100}, est) == 100 * eco.CLAUSE_VALUE_MAX
    assert eco.clause_share(CLAUSE, {"index_moves": {"raw": 0.10}}) == 0.55 * 0.05
    assert eco.clause_share(CLAUSE, {"index_moves": {}}) is None


def test_extreme_move_anchors_no_deeper_than_the_cap():
    case = stabilise_case()
    s = opened(case, Negotiator(case), move=0.48)
    assert s.terms.get("index_clause") == CLAUSE
    fixed = eco.value(case, {**s.terms, "index_clause": None, "unit_price": s.anchor}, s.est)
    with_clause = eco.value(case, s.terms, s.est)
    assert with_clause - fixed <= eco.CLAUSE_VALUE_MAX * s.anchor + 1e-6


def test_near_cost_supplier_keeps_a_relationship_target():
    case = stabilise_case()
    case["term_options"]["index_clause"] = [None]
    case["buyer"]["sustainable_margin_pct"] = 1
    s = opened(case, Negotiator(case), move=None, full_cost=15.2)  # at our cost estimate: 15 quoted
    assert s.target is not None
    assert s.budget == 0.14
    assert s.target <= s.quote
