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
