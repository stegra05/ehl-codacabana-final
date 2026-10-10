"""Quoted packages must survive evaluation and sending unchanged, without ID-specific rules."""

import copy

import pytest
from arena_kit.sim import load_cases

from buyer import economics as eco
from buyer.policy import Negotiator


def scenario():
    case = copy.deepcopy(load_cases()["case:S01"])
    case["case_id"] = "case:unseen"
    case["suppliers"] = ["sup:unseen"]
    case["negotiable"].append("index_clause")
    case["fixed_terms"].pop("index_clause")
    rising = {"series": "raw", "material_share": 0.5, "deadband_pct": 0, "base_month": "2026-08"}
    protected = {**rising, "deadband_pct": 5}
    case["term_options"]["index_clause"] = [None, rising, protected]
    case["buyer"]["index_paths"] = {"raw": 0.06}
    terms = eco.complete_offer(case, {"unit_price": 15, "payment_days": 30, "index_clause": rising})
    neg = Negotiator(case)
    event = {"from": "supplier", "status": "open", "body": "", "term_sheets": [{"terms": terms, "term_sheet_id": "q"}]}
    s = neg.setup("sup:unseen", [event])
    s.terms = terms.copy()
    s.ours = [14]
    return case, neg, s, terms, protected


@pytest.mark.parametrize("reverse", [False, True])
def test_higher_price_lower_total_cost_alternative_selected_whole(reverse):
    case, neg, s, terms, protected = scenario()
    better = {**terms, "unit_price": 15.1, "index_clause": protected}
    worse = {**terms, "unit_price": 15.2, "index_clause": protected}
    assert eco.cost(case, better) < eco.cost(case, terms)
    alts = [better, worse]
    if reverse:
        alts.reverse()
    neg.adopt(s, [{"terms": t} for t in [terms, *alts]])
    assert s.terms == better


def test_quoted_package_cannot_be_silently_snapped_or_override_fixed_terms():
    case, _, s, terms, _ = scenario()
    assert eco.quoted_offer(case, terms, s.std) == terms
    assert eco.quoted_offer(case, {**terms, "payment_days": 37}, s.std) is None
    field, value = next(iter(case["fixed_terms"].items()))
    assert eco.quoted_offer(case, {**terms, field: "not the fixed value"}, s.std) is None
    case["buyer"]["must_haves"] = [{"field": "payment_days", "op": ">=", "value": 60}]
    assert eco.quoted_offer(case, terms, s.std) is None


def test_finish_mirrors_exact_package_and_rejects_bad_alternatives():
    case, neg, s, terms, protected = scenario()
    better = {**terms, "unit_price": 15.1, "index_clause": protected}
    decision = neg.finish(
        s, [{"terms": terms}, {"terms": better}], [{"from": "supplier", "body": "Final quote"}], 15, 1
    )
    assert decision["message"]["term_sheets"] == [{"terms": better}]
    assert s.state == "mirror"
    s.state = "open"
    assert (
        neg.finish(
            s,
            [{"terms": terms}, {"terms": {**better, "payment_days": 37}}],
            [{"from": "supplier", "body": "Final quote"}],
            15,
            1,
        )
        is None
    )
    assert s.state == "done"


def test_payment_constraint_is_stated_without_model():
    case, neg, s, terms, _ = scenario()
    case["negotiable"].remove("payment_days")
    case["fixed_terms"]["payment_days"] = 30
    s.asks = ["payment"]
    decision = neg.send(s, [terms], [], [{"from": "supplier", "body": "Can you pay faster?"}], 15)
    assert "Payment is fixed at 30 days" in decision["message"]["body"]
    assert "pay reliably" not in decision["message"]["body"]


def test_explicit_fixed_price_does_not_depend_on_option_order():
    case, _, s, terms, protected = scenario()
    case["term_options"]["index_clause"] = [protected, None]
    fixed_price = {**terms, "index_clause": None}
    assert eco.quoted_offer(case, fixed_price, s.std) == fixed_price


def test_price_concession_does_not_justify_worse_package():
    case, neg, s, terms, _ = scenario()
    s.terms["payment_days"] = 90
    counter = {**terms, "unit_price": 14.99, "payment_days": 30}
    before = s.terms.copy()
    neg.adopt(s, [{"terms": counter}])
    assert s.terms == before
