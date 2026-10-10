"""End to end: our agent plays a case against arena-sim over HTTP, no network, no model."""

import json
import secrets
import socket
import threading
import time

import pytest
import uvicorn
from arena_kit import ArenaClient, RemoteTable, play
from arena_kit.sim import Sim, create_app, load_cases

from buyer.agent import agent_factory


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


def scripted(system, user):
    """A stand-in model: asks for a lower price, accepts once the supplier stops moving."""
    sid = ":".join(user.split("THREAD ")[1].split(":")[:2])
    if any(f"status {s}" in user for s in ("final_offer", "agreed")) or user.count("--- buyer") >= 8:
        return json.dumps({"supplier_id": sid, "action": "accept"})
    body = "Thank you for your quote. Could you send us a cost breakdown?"
    return json.dumps({"supplier_id": sid, "action": "send", "body": body, "term_sheets": [{"unit_price": 1.0}]})


def test_buyer_closes_a_deal(sim_url):
    key = ArenaClient(sim_url).register(f"test-{secrets.token_hex(3)}", "sim")["api_key"]
    client = ArenaClient(sim_url, key, rate=1000)
    result = play(RemoteTable(client), "case:S01", agent_factory("buyer", complete=scripted)())
    assert result["deal"]
    assert 0 <= result["score"] <= 1
