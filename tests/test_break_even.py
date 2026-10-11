"""The alternative as a ceiling: no sheet above the price where C meets C_alt, and one last sheet
at that ceiling when the supplier's final word is a deal we would refuse."""

import copy

from arena_kit.cost import complete_offer
from arena_kit.sim import load_cases

from buyer import economics as eco
from buyer.policy import Negotiator


def case_with_alternative(alt_price):
    case = copy.deepcopy(load_cases()["case:S01"])
    case["case_id"] = "case:break-even"
    alt = complete_offer(case, {"unit_price": alt_price, "payment_days": 60})
    case["buyer"]["alternative"] = {"kind": "quote", "terms": alt}
    return case


def reply(price, status="open"):
    terms = {"unit_price": price, "payment_days": 60}
    sheet = {"term_sheet_id": f"o{price}", "terms": terms}
    return {"from": "supplier", "status": status, "body": "", "term_sheets": [sheet]}


def test_break_even_is_the_last_price_cheaper_than_the_alternative():
    case = case_with_alternative(16.0)
    terms = complete_offer(case, {"unit_price": 15.0, "payment_days": 60})
    cap = eco.break_even(case, terms, {})
    assert eco.deal_cost(case, eco.at_price(terms, cap), {}) is not None
    assert eco.deal_cost(case, eco.at_price(terms, cap + 0.02), {}) is None
    assert eco.break_even(load_cases()["case:S01"], terms, {}) is None  # no alternative: no ceiling


def test_no_sheet_goes_above_the_alternative():
    case = case_with_alternative(14.0)  # below the usual anchor of 0.78 x 18
    neg = Negotiator(case)
    sid = case["suppliers"][0]
    events = [reply(18.0)]
    neg.setup(sid, events)
    first = neg.move(sid, {sid: events})["message"]["term_sheets"][0]["terms"]
    assert eco.deal_cost(case, first, {}) is not None
    neg.commit(sid)
    events += [{"from": "buyer", "term_sheets": [{"terms": first}]}, reply(17.0)]
    second = neg.move(sid, {sid: events})
    assert second is None or eco.deal_cost(case, second["message"]["term_sheets"][0]["terms"], {}) is not None


def test_a_final_above_the_alternative_gets_one_sheet_at_the_ceiling_then_stops():
    case = case_with_alternative(16.0)
    neg = Negotiator(case)
    sid = case["suppliers"][0]
    events = [reply(18.0)]
    s = neg.setup(sid, events)
    first = neg.move(sid, {sid: events})["message"]["term_sheets"][0]["terms"]
    neg.commit(sid)
    events += [{"from": "buyer", "term_sheets": [{"terms": first}]}, reply(16.5, "final_offer")]
    last = neg.move(sid, {sid: events})
    assert last is not None and s.state == "mirror"
    sheet = last["message"]["term_sheets"][0]["terms"]
    assert eco.deal_cost(case, sheet, {}) is not None
    assert sheet["unit_price"] == eco.break_even(case, s.terms, {}, s.est)
    neg.commit(sid)
    events += [{"from": "buyer", "term_sheets": [{"terms": sheet}]}, reply(16.5, "final_offer")]
    assert neg.move(sid, {sid: events}) is None  # one sheet, then the close decides


def test_relationship_cap_starts_inside_feasible_interval_not_at_zero():
    case = case_with_alternative(20.0)
    case["buyer"].update(category_goal="stabilise", relationship_eur_per_point=5000, sustainable_margin_pct=10)
    terms = complete_offer(case, {"unit_price": 15, "payment_days": 60})
    est = eco.estimate(case, {}, 0.07, full_cost=14)
    assert eco.cost(case, eco.at_price(terms, 0), {}, est) == float("inf")
    cap = eco.break_even(case, terms, {}, est)
    assert cap > 0
    assert eco.deal_cost(case, eco.at_price(terms, cap), {}, est) is not None


def test_no_feasible_package_opens_but_never_sends_zero_price():
    # no price at our terms beats the alternative on our estimate: we still open (its counters
    # bound the estimate), never with a 0.0 sheet, and the close gate walks if nothing beats it
    case = case_with_alternative(0.01)
    neg = Negotiator(case)
    sid = case["suppliers"][0]
    events = [reply(18)]
    neg.setup(sid, events)
    move = neg.move(sid, {sid: events})
    assert move is not None
    assert all(sheet["terms"]["unit_price"] > 0 for sheet in move["message"]["term_sheets"])
    assert neg.close({sid: events})["message"]["action"]["type"] == "walk_away"


def test_an_overshooting_cost_estimate_does_not_walk_before_the_first_sheet():
    # stabilise: a should-cost above the true full cost makes every price at our terms look dearer
    # than the alternative (relationship charge); the counter below it bounds the estimate and the
    # ceiling opens up, which a walk before the first sheet would never have seen
    case = case_with_alternative(17.0)
    case["buyer"].update(category_goal="stabilise", relationship_eur_per_point=20_000, sustainable_margin_pct=8)
    sid = case["suppliers"][0]
    neg = Negotiator(case)
    events = [reply(18.0)]
    s = neg.setup(sid, events)
    s.est["full_cost"], s.target = 17.2, None
    assert eco.break_even(case, s.terms, s.std, s.est) == 0.0
    first = neg.move(sid, {sid: events})
    assert first is not None
    neg.commit(sid)
    events += [{"from": "buyer", "term_sheets": first["message"]["term_sheets"]}, reply(15.5)]
    neg.move(sid, {sid: events})
    assert s.est["full_cost"] < 17.2
    assert eco.break_even(case, s.terms, s.std, s.est) > 0


def test_a_relationship_charge_does_not_drive_the_ceiling_to_zero():
    # below the supplier's full cost the relationship charge makes a lower price dearer (P01 sent a
    # 0.0 sheet): the ceiling is the top of the prices that beat the alternative
    case = case_with_alternative(16.0)
    case["buyer"].update(category_goal="secure_supply", relationship_eur_per_point=1_000, sustainable_margin_pct=5)
    sid = case["suppliers"][0]
    s = Negotiator(case).setup(sid, [reply(18.0)])
    est = {**s.est, "full_cost": 14.0}
    assert eco.cost(case, eco.at_price(s.terms, 0.01), s.std, est) > eco.c_alt(case)
    cap = eco.break_even(case, s.terms, s.std, est)
    assert cap is not None and cap > 14.0
    assert eco.deal_cost(case, eco.at_price(s.terms, cap), s.std, est) is not None
    assert eco.deal_cost(case, eco.at_price(s.terms, cap + 0.02), s.std, est) is None
