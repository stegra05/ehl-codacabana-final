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
from buyer.campaign import queue
from buyer.console import Console
from buyer.harvest import save
from buyer.moves import Prober
from buyer.suggest import Suggester


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


def test_probe_console_plays_defaults_and_harvests(sim_url, tmp_path):
    key = ArenaClient(sim_url).register(f"test-{secrets.token_hex(3)}", "sim")["api_key"]
    client = ArenaClient(sim_url, key, rate=1000)
    console = Console(client, "case:S01", auto_after=0, interactive=False, out=lambda *a: None)
    result = console.run()
    assert result["ended"]
    assert console.log and console.log[0]["key"] == "open"
    path = save(client, console.table.session_id, probe=console.log, root=tmp_path)
    saved = json.loads(path.read_text())
    assert saved["probe"] == console.log
    assert any(a.get("text") for ms in saved["messages"].values() for m in ms for a in m.get("attachments") or [])


def test_suggestions_pass_the_guard(sim_url):
    key = ArenaClient(sim_url).register(f"test-{secrets.token_hex(3)}", "sim")["api_key"]
    table = RemoteTable(ArenaClient(sim_url, key, rate=1000))
    case, threads = table.open("case:S01")
    sid = case["suppliers"][0]
    fake = {
        "suggestions": [
            {
                "label": "anchor",
                "tests": "floor",
                "action": "send",
                "body": "Our offer, see idx:NOPE@2026-01.",
                "term_sheets": [{"unit_price": 1.0}],
            },
            {"label": "take it", "tests": "-", "action": "accept"},
        ]
    }
    options = Suggester(lambda system, user: json.dumps(fake)).suggest(case, sid, threads, Prober(case))
    assert [o.key for o in options][0] == "a1"
    sent = options[0].message
    assert set(sent["term_sheets"][0]["terms"]) == set(case["negotiable"])
    assert "idx:NOPE" not in sent["body"]  # an unknown ID would cost trust


def test_campaign_queue_spreads_types_then_replays_the_weakest():
    cases = [
        {"case_id": f"case:P{i}", "type": t, "hosted": True}
        for i, t in [(1, "a"), (2, "a"), (3, "b"), (4, "c"), (5, "b")]
    ] + [{"case_id": "case:P9", "type": "a", "hosted": False}]
    assert queue(cases, [], {}, 15) == ["case:P1", "case:P3", "case:P4", "case:P2", "case:P5"]
    played = [{"case_id": c, "status": "ended"} for c in ("case:P1", "case:P2", "case:P3", "case:P4", "case:P5")]
    best = {"case:P1": 0.9, "case:P2": 0.1, "case:P3": 0.5, "case:P4": 0.0, "case:P5": 0.7}
    assert queue(cases, played, best, 7) == ["case:P4", "case:P2"]
