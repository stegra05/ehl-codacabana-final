"""Several bidders: once an acceptable sheet is agreed or final, a bidder whose deal at our latest
sheets cannot be cheaper gets no more rounds. Fake threads, no network, no model."""

import copy

import pytest
from arena_kit import complete_offer
from arena_kit.sim import load_cases

from buyer.policy import Negotiator


def case_and_terms():
    case = copy.deepcopy(load_cases()["case:S01"])
    return case, complete_offer(case, {"unit_price": 16.0, "payment_days": 60})


def reply(terms, price, status="open", oid="ts"):
    sheet = {"term_sheet_id": oid, "terms": {**terms, "unit_price": price}}
    return {"from": "supplier", "status": status, "body": "Our offer.", "term_sheets": [sheet]}


def ours(terms, *prices):
    return {
        "from": "buyer",
        "body": "Our proposal.",
        "term_sheets": [{"terms": {**terms, "unit_price": p}} for p in prices],
    }


def threads_with(terms, frozen_status, b_prices):
    return {
        "sup:a": [reply(terms, 16.0, oid="a0"), ours(terms, 14.0), reply(terms, 14.0, frozen_status, "a1")],
        "sup:b": [reply(terms, 16.5, oid="b0"), ours(terms, *b_prices), reply(terms, 15.5, oid="b1")],
    }


def negotiator(case, threads):
    neg = Negotiator(case)
    for sid, events in threads.items():
        neg.setup(sid, events[:1]).state = "open"
    return neg


@pytest.mark.parametrize("status", ["agreed", "final_offer"])
def test_a_bidder_that_cannot_beat_a_frozen_sheet_is_done(status):
    case, terms = case_and_terms()
    threads = threads_with(terms, status, [14.5])
    neg = negotiator(case, threads)
    neg.prune(threads)
    assert neg.sides["sup:b"].state == "done"
    assert neg.sides["sup:a"].state == "open"  # the frozen thread itself goes through finish()
    assert [n["supplier"] for n in neg.notes if n["what"] == "dominated"] == ["sup:b"]


def test_a_cheaper_sheet_of_ours_keeps_the_bidder_open():
    case, terms = case_and_terms()
    threads = threads_with(terms, "agreed", [14.5, 13.5])  # an alternative sheet below the frozen deal
    neg = negotiator(case, threads)
    neg.prune(threads)
    assert neg.sides["sup:b"].state == "open"


def test_no_frozen_or_no_acceptable_frozen_sheet_prunes_nothing(monkeypatch):
    case, terms = case_and_terms()
    threads = threads_with(terms, "open", [14.5])
    neg = negotiator(case, threads)
    neg.prune(threads)
    assert neg.sides["sup:b"].state == "open"
    threads = threads_with(terms, "agreed", [14.5])
    neg = negotiator(case, threads)
    monkeypatch.setattr("buyer.policy.eco.deal_cost", lambda *args: None)  # dearer than the alternative
    neg.prune(threads)
    assert neg.sides["sup:b"].state == "open"


@pytest.mark.parametrize("goal", ["stabilise", "secure_supply"])
@pytest.mark.parametrize("charge", [1000, 5000, 20000])
def test_relationship_cost_is_not_bounded_by_our_lower_price(goal, charge):
    from buyer import economics as eco

    case, terms = case_and_terms()
    case["buyer"].update(
        category_goal=goal,
        relationship_eur_per_point=charge,
        sustainable_margin_pct=10,
        alternative={"kind": "none"},
    )
    threads = {
        "sup:unseen-a": [reply(terms, 16), ours(terms, 16), reply(terms, 16, "agreed")],
        "sup:unseen-b": [reply(terms, 18), ours(terms, 14.5), reply(terms, 15.5)],
    }
    neg = negotiator(case, threads)
    for sid, side in neg.sides.items():
        side.est = eco.estimate(case, side.std, rate=0.1, full_cost=14 if sid.endswith("b") else 10)
    neg.prune(threads)
    assert not neg.sides["sup:unseen-b"].dominated
    assert neg.sides["sup:unseen-b"].state == "open"


def test_better_current_counter_is_not_discarded():
    case, terms = case_and_terms()
    threads = threads_with(terms, "agreed", [14.5])
    threads["sup:b"][-1] = reply(terms, 13.5, oid="better-counter")
    neg = negotiator(case, threads)
    neg.prune(threads)
    assert not neg.sides["sup:b"].dominated
    assert neg.best_offer(threads)[2] == "better-counter"


@pytest.mark.parametrize("valid", [True, False])
def test_quoted_alternative_is_checked_before_discarding_bidder(valid):
    case, terms = case_and_terms()
    threads = threads_with(terms, "agreed", [14.5])
    alternative = {**terms, "unit_price": 13.5}
    if not valid:
        case["buyer"]["must_haves"].append({"field": "payment_days", "op": ">=", "value": 30})
        alternative["payment_days"] = 14
    threads["sup:b"][-1]["term_sheets"].append({"term_sheet_id": "quoted-alternative", "terms": alternative})
    neg = negotiator(case, threads)
    neg.prune(threads)
    assert neg.sides["sup:b"].dominated is not valid
