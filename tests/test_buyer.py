"""End to end: our agent plays a case against arena-sim over HTTP, no network, no model; and the
term planner on a simulator case."""

import copy
import secrets

from arena_kit import ArenaClient, RemoteTable, complete_offer
from arena_kit.sim import load_cases

from buyer import economics, runner
from buyer.policy import Negotiator
from buyer.runner import play_case


def test_buyer_closes_a_deal(sim_url, tmp_path, monkeypatch):
    key = ArenaClient(sim_url).register(f"test-{secrets.token_hex(3)}", "sim")["api_key"]
    client = ArenaClient(sim_url, key, rate=1000)
    monkeypatch.setattr(runner, "RUNS", tmp_path)
    result = play_case(RemoteTable(client), "case:S01")
    assert result["deal"]
    assert 0 <= result["score"] <= 1


def test_terms_cover_the_need_when_the_price_is_low():
    """A 12-month contract leaves half a 2-year need to the fallback: at a low price we cover it."""
    case = copy.deepcopy(load_cases()["case:S01"])
    case["buyer"]["horizon_years"] = 2
    case["negotiable"].append("contract_months")
    case["fixed_terms"].pop("contract_months")
    case["term_options"]["contract_months"] = [12, 24]
    est = economics.estimate(case, {}, 0.07)
    quote = complete_offer(case, {"unit_price": case["buyer"]["current_unit_price"], "contract_months": 12})
    terms, c = economics.plan_terms(case, {}, est, quote, quote["unit_price"] * 0.8)
    assert terms["contract_months"] == 24
    assert c < economics.cost(case, {**quote, "unit_price": terms["unit_price"]}, {}, est)


def reply(status, terms, offer="offer:S-1"):
    return [{"from": "supplier", "status": status, "term_sheets": [{"term_sheet_id": offer, "terms": terms}]}]


def test_price_cut_does_not_justify_costlier_index_package():
    """A supplier's index clause on a rising series is taken only when its sheet, clause included,
    costs less than our planned package; never when it breaks a must-have."""
    case = copy.deepcopy(load_cases()["case:S01"])
    clause = {"series": "WB-CU", "material_share": 0.2, "deadband_pct": 0, "base_month": "2026-08"}
    case["negotiable"].append("index_clause")
    case["fixed_terms"].pop("index_clause")
    case["term_options"]["index_clause"] = [None, clause]
    case["buyer"]["index_paths"] = {"WB-CU": 0.05}
    quote = {"unit_price": 15.88, "payment_days": 30, "index_clause": None}

    def side(case):
        neg = Negotiator(case)
        s = neg.setup("sup:S", reply("open", quote))
        assert s.terms["index_clause"] is None
        s.ours.append(s.anchor)
        return neg, s

    neg, s = side(case)
    neg.adopt(s, [{"term_sheet_id": "offer:S-2", "terms": {**quote, "unit_price": 15.80, "index_clause": clause}}])
    assert s.terms["index_clause"] is None  # a token price cut does not pay for the clause
    neg.adopt(s, [{"term_sheet_id": "offer:S-3", "terms": {**quote, "unit_price": 14.0, "index_clause": clause}}])
    assert s.terms["index_clause"] is None  # a price cut alone does not justify worse terms

    case["buyer"]["must_haves"] = [{"field": "index_clause", "op": "==", "value": None}]
    neg, s = side(case)
    neg.adopt(s, [{"term_sheet_id": "offer:S-4", "terms": {**quote, "unit_price": 14.0, "index_clause": clause}}])
    assert s.terms["index_clause"] is None
