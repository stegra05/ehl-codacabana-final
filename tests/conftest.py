"""Fixtures: the data package from the repo, and arena-sim in-process with a clock the tests control."""

import socket
import threading
import time
from pathlib import Path

import pytest

DATA = Path(__file__).resolve().parents[1] / "negotiation-agent" / "negotiation-arena-kit" / "data"


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


@pytest.fixture(scope="session")
def pkg():
    from arena_kit.data import DataPackage

    return DataPackage(DATA)


@pytest.fixture
def sim():
    """arena-sim on a free local port: (base_url, Sim, Clock). Event code 'sim'."""
    pytest.importorskip("fastapi")
    import uvicorn
    from arena_kit.sim import Sim, create_app, load_cases

    clock = Clock()
    state = Sim(load_cases(), clock=clock)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(state), port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.01)
    yield f"http://127.0.0.1:{port}", state, clock
    server.should_exit = True
    thread.join()


@pytest.fixture
def no_kb(tmp_path, monkeypatch):
    """Point the knowledge base at a temp folder so tests never touch knowledge/."""
    from negotiator import personas

    monkeypatch.setattr(personas, "KB_DIR", tmp_path / "personas")
    monkeypatch.setattr(personas, "NEGOTIATIONS", tmp_path / "negotiations.jsonl")
    from negotiator import log

    monkeypatch.setattr(log, "MOVES", tmp_path / "moves.jsonl")
    monkeypatch.setattr(log, "CASES", tmp_path / "cases.jsonl")
    return tmp_path
