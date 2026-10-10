"""End to end: our agent plays a case against arena-sim over HTTP, no network, no model; and the
term planner on a simulator case."""

import copy
import secrets
import socket
import threading
import time

import pytest
import uvicorn
from arena_kit import ArenaClient, RemoteTable, complete_offer
from arena_kit.sim import Sim, create_app, load_cases

from buyer import economics, runner
from buyer.policy import Negotiator
from buyer.runner import play_case


@pytest.fixture
def sim_url():
    """arena-sim on a free local port, with a clock that never moves (no 60-second timeouts)."""
    server_state = Sim(load_cases(), clock=lambda: 1_000_000.0)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(server_state), port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.01)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join()


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


def test_close_never_beats_the_alternative():
    """A standing sheet dearer than the alternative is never accepted."""
    case = copy.deepcopy(load_cases()["case:S01"])
    case["buyer"]["alternative"] = {"kind": "quote", "ref": "quote:alt", "terms": {"unit_price": 10.0}}
    dear = {"unit_price": 15.88, "payment_days": 30}
    threads = {"sup:S": reply("final_offer", dear)}
    neg = Negotiator(case)
    neg.setup("sup:S", threads["sup:S"])
    assert economics.cost(case, dear, {}) > economics.c_alt(case)
    assert neg.close(threads)["message"]["action"]["type"] == "walk_away"


def test_adopts_its_index_clause_only_when_its_sheet_costs_less():
    """A supplier's index clause on a rising series is taken only when its sheet, clause included,
    costs less than its last one; never when it breaks a must-have."""
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
    assert s.terms["index_clause"] == clause  # a real cut does

    case["buyer"]["must_haves"] = [{"field": "index_clause", "op": "==", "value": None}]
    neg, s = side(case)
    neg.adopt(s, [{"term_sheet_id": "offer:S-4", "terms": {**quote, "unit_price": 14.0, "index_clause": clause}}])
    assert s.terms["index_clause"] is None
