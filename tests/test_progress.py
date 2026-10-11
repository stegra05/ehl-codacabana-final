"""Progress requires complete changed offers or new leverage; deadlines include the next call."""

import copy

import pytest
from arena_kit.sim import load_cases

from buyer import runner
from buyer.policy import Negotiator


def offer(price=18, payment=60, oid="a"):
    return {
        "from": "supplier",
        "term_sheets": [{"term_sheet_id": oid, "terms": {"unit_price": price, "payment_days": payment}}],
    }


def test_changed_payment_or_alternative_is_progress_even_at_same_price():
    events = [offer(oid="a"), offer(oid="b"), offer(oid="c")]
    assert Negotiator.offer_stalled(events)
    assert not Negotiator.offer_stalled(events[:2])
    assert not Negotiator.offer_stalled(events[:2] + [offer(payment=30)])
    alternative = copy.deepcopy(events[-1])
    alternative["term_sheets"].append({"terms": {"unit_price": 18, "payment_days": 90}})
    assert not Negotiator.offer_stalled(events[:2] + [alternative])
    assert not Negotiator.offer_stalled(events[:2] + [{"from": "arena", "term_sheets": []}])


@pytest.mark.parametrize("new_claim,new_trade,stop", [(False, False, True), (True, False, False), (False, True, False)])
def test_stall_closes_only_without_new_evidence_or_trade(monkeypatch, new_claim, new_trade, stop):
    case = copy.deepcopy(load_cases()["case:S01"])
    case["buyer"]["category_goal"] = "leverage"
    neg = Negotiator(case)
    sid = case["suppliers"][0]
    events = [offer(oid=str(i)) for i in range(3)]
    side = neg.setup(sid, events[:1])
    side.ours = [12]
    side.claims = []
    side.target = None
    monkeypatch.setattr(neg, "pick", lambda *args: [{"ids": ["doc:independent"]}] if new_claim else [])
    monkeypatch.setattr(neg, "need_trade_sheets", lambda s, t: [{**t, "payment_days": 30}] if new_trade else [])
    monkeypatch.setattr(neg, "send", lambda *args: {"message": "continue"})
    move = neg.move(sid, {sid: events})
    assert (move is None) == stop
    if stop:
        assert side.state == "done"
        assert any(n["what"] == "supplier_stalled" for n in neg.notes)


def test_stall_does_not_recommend_an_unacceptable_offer(monkeypatch):
    case = copy.deepcopy(load_cases()["case:S01"])
    case["buyer"]["category_goal"] = "leverage"
    neg = Negotiator(case)
    sid = case["suppliers"][0]
    events = [offer() for _ in range(3)]
    side = neg.setup(sid, events[:1])
    side.ours = [12]
    side.claims = []
    monkeypatch.setattr("buyer.policy.eco.deal_cost", lambda *args: None)
    monkeypatch.setattr(neg, "send", lambda *args: {"message": "continue"})
    assert neg.move(sid, {sid: events}) is not None


def test_keepalive_accounts_for_next_model_and_supplier_call():
    assert not runner.keepalive_due(20, 10, 10)
    assert runner.keepalive_due(20, 30, 10)  # less than old 35s trigger, but next call is too long
    assert runner.keepalive_due(36, 1, 1)
