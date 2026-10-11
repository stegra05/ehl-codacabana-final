"""A supplier price concession must not redefine the buyer's economic optimum."""

import copy

import pytest
from arena_kit.sim import load_cases

from buyer import economics as eco
from buyer.policy import Negotiator


def prepared():
    case = copy.deepcopy(load_cases()["case:S01"])
    case["case_id"] = "case:unseen-target"
    terms = eco.complete_offer(case, {"unit_price": 15, "payment_days": 60})
    event = {
        "from": "supplier",
        "status": "open",
        "body": "Our quote.",
        "term_sheets": [{"term_sheet_id": "quoted", "terms": terms}],
    }
    neg = Negotiator(case)
    side = neg.setup("sup:unseen", [event])
    side.terms = dict(terms)
    side.anchor = 14
    side.target = 14.8
    side.quote = 15
    side.est["full_cost"] = 14
    return neg, side, event


def test_initial_quote_does_not_replace_anchor_or_skip_claims(monkeypatch):
    neg, side, event = prepared()
    side.target = 16

    def forbidden(*args):
        raise AssertionError("Unchanged opening economics must preserve setup target")

    monkeypatch.setattr(eco, "relationship_optimum", forbidden)
    decision = neg.move(side.sid, {side.sid: [event]})
    assert decision["message"]["term_sheets"][0]["terms"]["unit_price"] == 14
    assert side.state == "open"
    assert side.target == 16


def test_price_only_reply_does_not_recalculate_target(monkeypatch):
    neg, side, event = prepared()
    side.ours = [14]
    side.theirs = [15]
    side.last_reply = object()
    event["term_sheets"][0]["terms"]["unit_price"] = 14.82
    monkeypatch.setattr(eco, "relationship_optimum", lambda *args: (_ for _ in ()).throw(AssertionError()))
    neg.move(side.sid, {side.sid: [event]})
    assert side.target == 14.8
    assert side.state == "open"  # 0.2% proximity is not an economic reason to close
    assert side.ours[-1] < 14.82


@pytest.mark.parametrize("counter", [14.8, 14.7])
def test_counter_at_or_below_target_closes_on_standing_sheet(counter):
    neg, side, event = prepared()
    side.ours = [14]
    side.theirs = [15]
    side.last_reply = object()
    event["term_sheets"][0]["terms"]["unit_price"] = counter
    threads = {side.sid: [event]}

    assert neg.move(side.sid, threads) is None
    assert side.state == "done"
    assert side.ours == [14]  # no new sheet above the supplier's counter
    assert neg.close(threads)["message"]["action"] == {"type": "accept", "term_sheet_id": "quoted"}


def test_changed_economics_refresh_target_without_clipping_search(monkeypatch):
    neg, side, event = prepared()
    side.ours = [14]
    side.theirs = [15]
    side.last_reply = object()
    side.target = 16
    event["term_sheets"][0]["terms"]["unit_price"] = 14.7

    def update(s, body):
        s.est["interest_rate"] += 0.01

    neg.read_signals = update
    bounds = []

    def optimum(case, terms, std, est, lo, hi):
        bounds.append((lo, hi))
        return 16

    monkeypatch.setattr(eco, "relationship_optimum", optimum)
    assert neg.move(side.sid, {side.sid: [event]}) is None
    assert len(bounds) == 1
    assert bounds[0][1] >= 16
    assert side.target == 16
    assert side.ours == [14]
    assert side.state == "done"


def test_a_counter_below_our_cost_estimate_bounds_it_and_moves_the_target():
    """A supplier does not offer below its cost: its counter caps the full-cost estimate, the
    target follows, and we step toward the counter instead of closing above it (P01)."""
    neg, side, event = prepared()
    neg.case["buyer"].update(category_goal="stabilise", sustainable_margin_pct=1, relationship_eur_per_point=2000)
    side.ours = [14]
    side.theirs = [15]
    side.last_reply = object()
    side.est["full_cost"] = 14.9
    side.target = 14.8
    event["term_sheets"][0]["terms"]["unit_price"] = 14.7  # below the target: the old path closed at 14.8
    decision = neg.move(side.sid, {side.sid: [event]})
    assert side.est["full_cost"] <= 14.7
    assert side.target < 14.7
    assert side.state == "open"
    assert decision["message"]["term_sheets"][0]["terms"]["unit_price"] < 14.7


def test_a_counter_the_supplier_values_above_our_estimate_leaves_it(monkeypatch):
    """A clause the supplier values keeps a low price above its cost in its own valuation (P02)."""
    neg, side, event = prepared()
    side.ours = [14]
    side.theirs = [15]
    side.last_reply = object()
    side.est["full_cost"] = 14.9
    monkeypatch.setattr(eco, "value", lambda case, terms, est: terms["unit_price"] * 1.08)
    event["term_sheets"][0]["terms"]["unit_price"] = 14.0
    neg.move(side.sid, {side.sid: [event]})
    assert side.est["full_cost"] == 14.9
