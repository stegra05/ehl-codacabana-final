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
