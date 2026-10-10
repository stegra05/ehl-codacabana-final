"""Fixtures: arena-sim in-process with a clock that never moves, the kit's simulator cases, and
the data package when it is on disk (`uv run arena data`); tests that need it skip otherwise."""

import json
import os
import socket
import threading
import time
from pathlib import Path

import pytest
from arena_kit import sim
from arena_kit.sim import Sim, create_app, load_cases

SIM_CASES = Path(sim.__file__).parent / "sim_cases"


@pytest.fixture
def sim_url():
    """arena-sim on a free local port, with a clock that never moves (no 60-second timeouts)."""
    server_state = Sim(load_cases(), clock=lambda: 1_000_000.0)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn_server(create_app(server_state), port)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.01)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join()


def uvicorn_server(app, port):
    import uvicorn

    return uvicorn.Server(uvicorn.Config(app, port=port, log_level="warning"))


@pytest.fixture(scope="session")
def pkg():
    from arena_kit.data import DataPackage

    root = Path(os.environ.get("ARENA_DATA") or "data/package")
    if not (root / "facts.json").is_file():
        pytest.skip("no data package on disk: run `uv run arena data`")
    return DataPackage(root)


@pytest.fixture
def sim_case():
    return lambda name: json.loads((SIM_CASES / f"{name}.json").read_text())


@pytest.fixture(autouse=True)
def no_logs(tmp_path, monkeypatch):
    """Logs go to a temp folder so tests never touch logs/."""
    from buyer import log

    monkeypatch.setattr(log, "MOVES", tmp_path / "moves.jsonl")
    monkeypatch.setattr(log, "CASES", tmp_path / "cases.jsonl")
    monkeypatch.setattr(log, "PLANS", tmp_path / "plans.jsonl")
    return tmp_path
