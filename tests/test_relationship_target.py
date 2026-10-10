"""A supplier price concession must not redefine the buyer's economic optimum."""

import copy

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
    neg.move(side.sid, {side.sid: [event]})
    assert len(bounds) == 1
    assert bounds[0][1] >= 16
    assert side.ours[-1] == 16
